"""Verify one retrospective candidate with NVDA-only evidence."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.adaptor.llm_response import ToolCallConversionError
from a11y_gent.config import RunConfig
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import SerializedToolCall, deserialize_tool_call, serialize_tool_call
from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import (
    Candidate,
    ExecutionError,
    VerificationOutcome,
    VerificationOutcomeStatus,
    WorkflowTask,
)
from a11y_gent.prompts import build_verify_prompt, make_verify_completion_tool
from a11y_gent.runtime.action_contract import rejected_action, validate_action


class VerificationState(TypedDict):
    """State persisted for one candidate verification."""

    task: WorkflowTask
    candidate_reference: int
    candidate: Candidate
    history: list[Message]
    pending_tool_calls: list[SerializedToolCall]
    pending_observations: list[Message]
    reason_action: Message | None
    step_count: int
    outcome: VerificationOutcome | None


async def verify_candidate(
    config: RunConfig,
    llm: LlmClient,
    task: WorkflowTask,
    candidate_reference: int,
    candidate: Candidate,
    nvda_tools: list[Tool],
) -> VerificationOutcome:
    """Verify one candidate through a fresh NVDA-only interaction loop."""
    graph = build_verification_graph(
        llm,
        config.model,
        config.nvda_max_steps,
        [*nvda_tools, make_verify_completion_tool()],
    )
    state = await graph.ainvoke(initial_verification_state(task, candidate_reference, candidate))
    if state["outcome"] is not None:
        return state["outcome"]
    return {
        "candidate_reference": candidate_reference,
        "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
        "evidence": f"The NVDA interaction limit of {config.nvda_max_steps} was reached.",
    }


def build_verification_graph(llm: LlmClient, model: str, max_steps: int, tools: list[Tool]):
    graph = StateGraph(VerificationState)
    graph.add_node("reason", _reason_node(llm, model, tools))
    graph.add_node("act", _act_node(llm, model, tools))
    graph.add_node("observe", _observe_node(llm, tools))
    graph.add_edge(START, "reason")
    graph.add_edge("reason", "act")
    graph.add_edge("act", "observe")
    graph.add_conditional_edges("observe", _after_observe(max_steps), {"reason": "reason", "done": END})
    return graph.compile()


def initial_verification_state(
    task: WorkflowTask, candidate_reference: int, candidate: Candidate
) -> VerificationState:
    return {
        "task": task,
        "candidate_reference": candidate_reference,
        "candidate": candidate,
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "verify",
                "content": build_verify_prompt(task, candidate_reference, candidate),
            }
        ],
        "pending_tool_calls": [],
        "pending_observations": [],
        "reason_action": None,
        "step_count": 0,
        "outcome": None,
    }


def _reason_node(llm: LlmClient, model: str, tools: list[Tool]):
    async def reason(state: VerificationState) -> VerificationState:
        try:
            response = await llm.infer(state["history"], model)
        except ToolCallConversionError as error:
            action, _ = rejected_action(error)
            return {**state, "reason_action": action}
        calls = [serialize_tool_call(call) for call in response.get("tool_calls", [])]
        action = _action_message(response["message"], calls)
        return {
            **state,
            "history": [*state["history"], _action_message(response["message"], [])],
            "reason_action": action if calls else None,
        }

    return reason


def _act_node(llm: LlmClient, model: str, tools: list[Tool]):
    async def act(state: VerificationState) -> VerificationState:
        try:
            response = await llm.infer(state["history"], model)
        except ToolCallConversionError as error:
            action, observation = rejected_action(error)
            return {
                **state,
                "history": [*state["history"], action],
                "pending_tool_calls": [],
                "pending_observations": [observation],
                "reason_action": None,
                "step_count": state["step_count"] + 1,
            }
        calls = [serialize_tool_call(call) for call in response.get("tool_calls", [])]
        action = _action_message(response["message"], calls)
        selected_action = action if calls or state["reason_action"] is None else state["reason_action"]
        validation = validate_action(selected_action, {tool["name"]: tool for tool in tools})
        return {
            **state,
            "history": [*state["history"], selected_action],
            "pending_tool_calls": validation["pending_tool_calls"],
            "pending_observations": validation["observations"],
            "reason_action": None,
            "step_count": state["step_count"] + 1,
        }

    return act


def _observe_node(llm: LlmClient, tools: list[Tool]):
    tools_by_name = {tool["name"]: tool for tool in tools}

    async def observe(state: VerificationState) -> VerificationState:
        history = list(state["history"])
        outcome = state["outcome"]
        history.extend(state["pending_observations"])
        for call in state["pending_tool_calls"]:
            try:
                history.append(await llm.execute_tool_call(deserialize_tool_call(call, tools_by_name)))
            except Exception as error:
                outcome = _execution_error_outcome(state, str(error))
                break
            if call["tool"]["name"] == "complete_verification":
                outcome = _outcome(state["candidate_reference"], call["arguments"])
        return {
            **state,
            "history": history,
            "outcome": outcome,
            "pending_tool_calls": [],
            "pending_observations": [],
        }

    return observe


def _execution_error_outcome(state: VerificationState, message: str) -> VerificationOutcome:
    error: ExecutionError = {
        "task_number": state["task"]["number"],
        "phase": "verify",
        "candidate_reference": state["candidate_reference"],
        "message": message,
    }
    return {
        "candidate_reference": state["candidate_reference"],
        "status": VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR,
        "evidence": message,
        "execution_error": error,
    }


def _after_observe(max_steps: int):
    def continue_or_stop(state: VerificationState) -> str:
        if state["outcome"] is not None or state["step_count"] >= max_steps:
            return "done"
        return "reason"

    return continue_or_stop


def _outcome(candidate_reference: int, arguments: dict) -> VerificationOutcome:
    try:
        status = VerificationOutcomeStatus(str(arguments["status"]))
    except ValueError as error:
        raise RuntimeError("Verification must use a supported outcome status") from error
    outcome: VerificationOutcome = {
        "candidate_reference": candidate_reference,
        "status": status,
        "evidence": str(arguments["evidence"]),
    }
    if status is VerificationOutcomeStatus.CONFIRMED:
        outcome["confirmed_barrier"] = _barrier(arguments)
    elif status is VerificationOutcomeStatus.DISCARDED:
        if not outcome["evidence"].strip():
            raise RuntimeError("Discarded verification requires disconfirming evidence")
    else:
        raise RuntimeError("Only runtime failures may leave verification unverified")
    return outcome


def _barrier(arguments: dict) -> Barrier:
    fields = ("description", "expected_behavior", "actual_behavior", "reproduction_steps", "evidence")
    if any(not arguments.get(field) for field in fields):
        raise RuntimeError("Confirmed verification requires a complete barrier")
    reproduction_steps = arguments["reproduction_steps"]
    if not isinstance(reproduction_steps, list) or any(
        not isinstance(step, str) or not step.strip() for step in reproduction_steps
    ):
        raise RuntimeError("Confirmed verification requires reproduction steps as a non-empty list of sentences")
    return {
        "description": str(arguments["description"]),
        "expected_behavior": str(arguments["expected_behavior"]),
        "actual_behavior": str(arguments["actual_behavior"]),
        "reproduction_steps": reproduction_steps,
        "evidence": str(arguments["evidence"]),
    }


def _action_message(message: Message, calls: list[SerializedToolCall]) -> Message:
    action: Message = {
        **{key: value for key, value in message.items() if key != "tool_calls"},
    }
    if calls:
        action["tool_calls"] = calls
    return action