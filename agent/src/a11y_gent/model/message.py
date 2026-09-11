from enum import Enum
from typing import NotRequired, TypedDict

from a11y_gent.model.tool_call import ToolCall



class MessageOrigin(Enum):
    SYSTEM = "system"
    USER = "user"
    TOOL = "tool"
    ASSISTANT = "assistant"

    def __str__(self) -> str:
        return self.value

class Message(TypedDict):
    origin: MessageOrigin
    content: str
    name: str
    reference_id: NotRequired[str]
    tool_calls: NotRequired[list[ToolCall]]


