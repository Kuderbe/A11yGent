"""Generate unverified candidates from one immutable solve-task history."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import SerializedToolCall, deserialize_tool_call, serialize_tool_call
from a11y_gent.model.workflow import Candidate, WorkflowTask
from a11y_gent.prompts import build_retrospective_prompt, make_retrospective_completion_tool
from a11y_gent.tooling.extract import extract_barriers


class RetrospectiveState(TypedDict):
    """State persisted for one retrospective analysis."""

    history: list[Message]
    candidates: list[Candidate]


async def retrospect(
    task: WorkflowTask,
    solve_task_history: list[Message],
    llm: LlmClient,
    model: str,
) -> list[Candidate]:
    """Generate unverified candidates from one completed solve-task history."""
    graph = _build_graph(
        task,
        solve_task_history,
        llm,
        make_retrospective_completion_tool(),
        model,
    )
    state = await graph.ainvoke(_initial_state(task, solve_task_history))
    return state["candidates"]


def _build_graph(
    task: WorkflowTask,
    solve_task_history: list[Message],
    llm: LlmClient,
    completion_tool: Tool,
    model: str,
):
    graph = StateGraph(RetrospectiveState)
    graph.add_node("analyze", _analyze_node(model, task, solve_task_history, llm, completion_tool))
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", END)
    return graph.compile()


def _initial_state(task: WorkflowTask, solve_task_history: list[Message]) -> RetrospectiveState:
    return {
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "retrospective",
                "content": build_retrospective_prompt(task, solve_task_history),
            }
        ],
        "candidates": [],
    }


def _analyze_node(
    model: str,
    task: WorkflowTask,
    solve_task_history: list[Message],
    llm: LlmClient,
    completion_tool: Tool,
):
    async def analyze(state: RetrospectiveState) -> RetrospectiveState:
        response = await llm.infer(state["history"], model)
        tool_calls = response.get("tool_calls", [])
        if len(tool_calls) != 1 or tool_calls[0]["tool"]["name"] != "complete_retrospective":
            raise RuntimeError("Retrospective must complete with exactly one complete_retrospective call")
        call = tool_calls[0]
        serialized_call = serialize_tool_call(call)
        tool_result = await llm.execute_tool_call(
            deserialize_tool_call(serialized_call, {completion_tool["name"]: completion_tool})
        )
        candidates = _candidates(task, solve_task_history, call["arguments"])
        return {
            "history": [
                *state["history"],
                _action_message(response["message"], serialized_call),
                tool_result,
            ],
            "candidates": candidates,
        }

    return analyze


def _candidates(
    task: WorkflowTask, solve_task_history: list[Message], arguments: dict
) -> list[Candidate]:
    descriptions = [str(description) for description in arguments["descriptions"]]
    verification_briefs = [str(brief) for brief in arguments["verification_briefs"]]
    if len(descriptions) != len(verification_briefs):
        raise RuntimeError("Retrospective descriptions and verification briefs must have matching lengths")
    reported = {_normalize(barrier["description"]) for barrier in extract_barriers(solve_task_history)}
    return [
        {
            "task_number": task["number"],
            "description": description,
            "verification_brief": verification_brief,
        }
        for description, verification_brief in zip(descriptions, verification_briefs)
        if _normalize(description) not in reported
    ]


def _action_message(message: Message, tool_call: SerializedToolCall) -> Message:
    return {
        **{key: value for key, value in message.items() if key != "tool_calls"},
        "tool_calls": [tool_call],
    }


def _normalize(description: str) -> str:
    return " ".join(description.lower().split())