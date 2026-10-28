"""Validate native action calls and create recoverable observations."""

import inspect
from typing import TypedDict

from a11y_gent.adaptor.llm_response import ToolCallConversionError
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import SerializedToolCall


class ActionValidation(TypedDict):
    pending_tool_calls: list[SerializedToolCall]
    observations: list[Message]


def validate_action(action: Message, tools_by_name: dict[str, Tool]) -> ActionValidation:
    """Return one executable call or observations explaining why none can run."""
    calls = action.get("tool_calls", [])
    if len(calls) != 1:
        return {
            "pending_tool_calls": [],
            "observations": _count_observations(calls),
        }

    call = calls[0]
    error = _call_error(call, tools_by_name)
    if error is not None:
        return {"pending_tool_calls": [], "observations": [_observation(call, error)]}
    return {"pending_tool_calls": [call], "observations": []}


def rejected_action(error: ToolCallConversionError) -> tuple[Message, Message]:
    """Return a provider-compatible rejected action and its observation."""
    call: SerializedToolCall = {
        "id": error.call_id,
        "tool": {"name": error.tool_name, "description": ""},
        "arguments": {},
    }
    action: Message = {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [call],
    }
    return action, _observation(call, str(error))


def _count_observations(calls: list[SerializedToolCall]) -> list[Message]:
    message = f"Action rejected: exactly one tool call is required; received {len(calls)}. No requested tool was executed."
    if calls:
        return [_observation(call, message) for call in calls]
    return [{"origin": MessageOrigin.USER, "name": "action_contract", "content": message}]


def _call_error(call: SerializedToolCall, tools_by_name: dict[str, Tool]) -> str | None:
    name = call["tool"]["name"]
    tool = tools_by_name.get(name)
    if tool is None:
        return f"Action rejected: unknown tool '{name}'. No requested tool was executed."
    try:
        inspect.signature(tool["tool_function"]).bind(**call["arguments"])
    except TypeError as error:
        return f"Action rejected: invalid arguments for '{name}': {error}. No requested tool was executed."
    return None


def _observation(call: SerializedToolCall, content: str) -> Message:
    return {
        "origin": MessageOrigin.TOOL,
        "name": call["tool"]["name"],
        "content": content,
        "reference_id": call["id"],
    }