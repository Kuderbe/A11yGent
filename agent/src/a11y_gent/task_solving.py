"""Execute one NVDA-only task attempt in a checkpointed LangGraph stage."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import SerializedToolCall, deserialize_tool_call, serialize_tool_call
from a11y_gent.model.verdict import Verdict, VerdictStatus
from a11y_gent.model.workflow import WorkflowTask
from a11y_gent.prompts import build_solve_task_prompt, make_solve_task_completion_tool
from a11y_gent.runtime.reasoning import assert_plain_text_reasoning
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.extract import extract_barriers


class SolveTaskState(TypedDict):
    """State persisted for one solve-task attempt."""

    history: list[Message]
    completed: bool
    status: str
    summary: str
    pending_tool_calls: list[SerializedToolCall]
    step_count: int


async def solve_task(
    config: RunConfig,
    llm: LlmClient,
    task: WorkflowTask,
    nvda_tools: list[Tool],
) -> Verdict:
    """Attempt one task with NVDA tools and local direct-reporting sinks only."""
    graph = build_solve_task_graph(
        config,
        llm,
        [*nvda_tools, make_barrier_tool(), make_solve_task_completion_tool()],
    )
    state = await graph.ainvoke(initial_solve_task_state(task))
    barriers = extract_barriers(state["history"])
    if state["completed"]:
        return {"status": _status(state["status"]), "summary": state["summary"], "barriers": barriers}
    return {
        "status": VerdictStatus.FAILED,
        "summary": f"The task could not be solved within {config.nvda_max_steps} steps.",
        "barriers": barriers,
    }


def build_solve_task_graph(config: RunConfig, llm: LlmClient, tools: list[Tool]):
    graph = StateGraph(SolveTaskState)
    graph.add_node("reason", _reason_node(llm, config.model))
    graph.add_node("act", _act_node(llm, config.model))
    graph.add_node("observe", _observe_node(llm, tools))
    graph.add_edge(START, "reason")
    graph.add_edge("reason", "act")
    graph.add_conditional_edges("act", _after_act, {"observe": "observe", "reason": "reason"})
    graph.add_conditional_edges("observe", _after_observe(config.nvda_max_steps), {"reason": "reason", "done": END})
    return graph.compile()


def initial_solve_task_state(task: WorkflowTask) -> SolveTaskState:
    return {
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "solve_task",
                "content": build_solve_task_prompt(task),
            }
        ],
        "completed": False,
        "status": "",
        "summary": "",
        "pending_tool_calls": [],
        "step_count": 0,
    }


def _reason_node(llm: LlmClient, model: str):
    async def reason(state: SolveTaskState) -> SolveTaskState:
        response = await llm.infer(state["history"], model, use_tools=False)
        assert_plain_text_reasoning(response["message"]["content"])
        return {**state, "history": [*state["history"], response["message"]]}

    return reason


def _act_node(llm: LlmClient, model: str):
    async def act(state: SolveTaskState) -> SolveTaskState:
        response = await llm.infer(state["history"], model)
        tool_calls = response.get("tool_calls", [])
        if len(tool_calls) != 1:
            raise RuntimeError("Solve task action turns must contain exactly one tool call")
        calls = [serialize_tool_call(call) for call in tool_calls]
        return {
            **state,
            "history": [*state["history"], _action_message(response["message"], calls)],
            "pending_tool_calls": calls,
            "step_count": state["step_count"] + 1,
        }

    return act


def _observe_node(llm: LlmClient, tools: list[Tool]):
    tools_by_name = {tool["name"]: tool for tool in tools}

    async def observe(state: SolveTaskState) -> SolveTaskState:
        history = list(state["history"])
        completed = state["completed"]
        status = state["status"]
        summary = state["summary"]
        for call in state["pending_tool_calls"]:
            history.append(await llm.execute_tool_call(deserialize_tool_call(call, tools_by_name)))
            if call["tool"]["name"] == "complete_solve_task":
                completed = True
                status = str(call["arguments"]["status"])
                summary = str(call["arguments"]["summary"])
        return {
            **state,
            "history": history,
            "completed": completed,
            "status": status,
            "summary": summary,
            "pending_tool_calls": [],
        }

    return observe


def _after_act(state: SolveTaskState) -> str:
    return "observe" if state["pending_tool_calls"] else "reason"


def _after_observe(max_steps: int):
    def continue_or_stop(state: SolveTaskState) -> str:
        if state["completed"] or state["step_count"] >= max_steps:
            return "done"
        return "reason"

    return continue_or_stop


def _action_message(message: Message, calls: list[SerializedToolCall]) -> Message:
    return {
        **{key: value for key, value in message.items() if key != "tool_calls"},
        "tool_calls": calls,
    }


def _status(value: str) -> VerdictStatus:
    try:
        return VerdictStatus(value)
    except ValueError:
        return VerdictStatus.FAILED