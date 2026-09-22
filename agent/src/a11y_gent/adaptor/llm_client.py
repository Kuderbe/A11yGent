from abc import ABC, abstractmethod
from a11y_gent.adaptor.llm_response import LlmResponse
from a11y_gent.model.message import Message
from a11y_gent.model.tool_call import ToolCall

class LlmClient(ABC):

    @abstractmethod
    async def infer(
        self, history: list[Message], model: str, use_tools: bool = True
    ) -> LlmResponse:
        """Infer the next message from a history of messages.

        When ``use_tools`` is ``False`` the model responds with plain text only
        (no tool calls).
        """

    @abstractmethod
    async def execute_tool_call(self, tool_call: ToolCall) -> Message:
        """Executes a tool call and returns the corresponding tool-result message"""