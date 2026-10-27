"""Generate unverified candidates from one immutable solve-task history."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import SerializedToolCall, deserialize_tool_call, serialize_tool_call
from a11y_gent.model.workflow import Candidate, WorkflowTask
from a11y_gent.prompts import (
    build_retrospective_prompt,
    make_candidate_creation_tool,
    make_retrospective_completion_tool,
)
from a11y_gent.tooling.extract import extract_barriers


class RetrospectiveState(TypedDict):
    """State persisted for one retrospective analysis."""

    task: WorkflowTask
    solve_task_history: list[Message]
    history: list[Message]
    candidates: list[Candidate]
    iterations: int


async def retrospect(
    task: WorkflowTask,
    solve_task_history: list[Message],
    llm: LlmClient,
    model: str,
    max_iterations: int,
) -> list[Candidate]:
    """Generate unverified candidates from one completed solve-task history."""
    graph = build_retrospective_graph(
        llm, make_candidate_creation_tool(), make_retrospective_completion_tool(), model, max_iterations
    )
    state = await graph.ainvoke(initial_retrospective_state(task, solve_task_history))
    return state["candidates"]


def build_retrospective_graph(
    llm: LlmClient,
    candidate_tool: Tool,
    completion_tool: Tool,
    model: str,
    max_iterations: int,
):
    graph = StateGraph(RetrospectiveState)
    graph.add_node("analyze", _analyze_node(model, llm, candidate_tool, completion_tool, max_iterations))
    graph.add_edge(START, "analyze")
    graph.add_conditional_edges("analyze", _next_node, {"analyze": "analyze", "complete": END})
    return graph.compile()


def initial_retrospective_state(
    task: WorkflowTask, solve_task_history: list[Message]
) -> RetrospectiveState:
    return {
        "task": task,
        "solve_task_history": solve_task_history,
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "retrospective",
                "content": build_retrospective_prompt(task, solve_task_history),
            }
        ],
        "candidates": [],
        "iterations": 0,
    }


def _analyze_node(
    model: str,
    llm: LlmClient,
    candidate_tool: Tool,
    completion_tool: Tool,
    max_iterations: int,
):
    async def analyze(state: RetrospectiveState) -> RetrospectiveState:
        if state["iterations"] >= max_iterations:
            raise RuntimeError("Retrospective exceeded its iteration budget")
        response = await llm.infer(state["history"], model)
        tool_calls = response.get("tool_calls", [])
        if len(tool_calls) != 1 or tool_calls[0]["tool"]["name"] not in {"create_candidate", "complete_retrospective"}:
            raise RuntimeError("Retrospective must make exactly one create_candidate or complete_retrospective call")
        call = tool_calls[0]
        serialized_call = serialize_tool_call(call)
        tool_result = await llm.execute_tool_call(
            deserialize_tool_call(
                serialized_call,
                {candidate_tool["name"]: candidate_tool, completion_tool["name"]: completion_tool},
            )
        )
        candidates = state["candidates"]
        if call["tool"]["name"] == "create_candidate":
            candidate = _candidate(state["solve_task_history"], call["arguments"])
            if candidate is not None:
                candidates = [*candidates, candidate]
        return {
            "task": state["task"],
            "solve_task_history": state["solve_task_history"],
            "history": [
                *state["history"],
                _action_message(response["message"], serialized_call),
                tool_result,
            ],
            "candidates": candidates,
            "iterations": state["iterations"] + 1,
        }

    return analyze


def _candidate(solve_task_history: list[Message], arguments: dict) -> Candidate | None:
    description = str(arguments["description"])
    reported = {_normalize(barrier["description"]) for barrier in extract_barriers(solve_task_history)}
    if _normalize(description) in reported:
        return None
    return {"description": description, "verification_brief": str(arguments["verification_brief"])}


def _next_node(state: RetrospectiveState) -> str:
    return "complete" if _is_completed(state["history"]) else "analyze"


def _is_completed(history: list[Message]) -> bool:
    return any(
        call["tool"]["name"] == "complete_retrospective"
        for message in history
        for call in message.get("tool_calls", [])
    )


def _action_message(message: Message, tool_call: SerializedToolCall) -> Message:
    return {
        **{key: value for key, value in message.items() if key != "tool_calls"},
        "tool_calls": [tool_call],
    }


def _normalize(description: str) -> str:
    return " ".join(description.lower().split())