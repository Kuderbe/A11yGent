from typing import NotRequired, TypedDict

from a11y_gent.model.message import Message
from a11y_gent.model.tool_call import ToolCall


class LlmResponse(TypedDict):
    message: Message
    tool_calls: NotRequired[list[ToolCall]]