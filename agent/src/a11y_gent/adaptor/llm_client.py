from abc import ABC, abstractmethod
from a11y_gent.adaptor.llm_response import LlmResponse
from a11y_gent.model.message import Message
from a11y_gent.model.tool_call import ToolCall

class LlmClient(ABC):

    @abstractmethod
    def infer(self, history: list[Message], model: str) -> LlmResponse:
        """Inferrs the next message from a history of messages"""

    @abstractmethod
    def execute_tool_call(self, tool_call: ToolCall) -> Message:
        """Executes a tool call and returns the corresponding tool-result message"""