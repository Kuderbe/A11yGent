from typing import Any, TypedDict

from a11y_gent.model.tool import SerializedTool, Tool


class SerializedToolCall(TypedDict):
    """A serializable tool call retained in an LLM conversation history."""

    id: str
    tool: SerializedTool
    arguments: dict[str, Any]


class ToolCall(TypedDict):
    """An executable tool call with its locally registered capability."""

    id: str
    tool: Tool
    arguments: dict[str, Any]


def serialize_tool_call(tool_call: ToolCall) -> SerializedToolCall:
    """Drop the executable function before retaining a tool call in history."""
    return {
        "id": tool_call["id"],
        "tool": {
            "name": tool_call["tool"]["name"],
            "description": tool_call["tool"]["description"],
        },
        "arguments": tool_call["arguments"],
    }


def deserialize_tool_call(
    tool_call: SerializedToolCall, tools_by_name: dict[str, Tool]
) -> ToolCall:
    """Restore an executable call from its local tool capability."""
    return {
        "id": tool_call["id"],
        "tool": tools_by_name[tool_call["tool"]["name"]],
        "arguments": tool_call["arguments"],
    }