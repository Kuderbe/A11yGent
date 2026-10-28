from typing import NotRequired, TypedDict

from a11y_gent.model.message import Message
from a11y_gent.model.tool_call import ToolCall


class ToolCallConversionError(ValueError):
    """A native tool call that cannot become an executable local call."""

    def __init__(self, call_id: str, tool_name: str, arguments_raw: str, message: str):
        super().__init__(message)
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments_raw = arguments_raw


class LlmResponse(TypedDict):
    message: Message
    tool_calls: NotRequired[list[ToolCall]]