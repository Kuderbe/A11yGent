from typing import TypedDict

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import Message
from a11y_gent.model.task import Task
from a11y_gent.model.tool_call import ToolCall


class GraphState(TypedDict):
    llm: LlmClient
    task: Task
    model: str
    max_steps: int

    discovery_context: list[Message]
    pending_tool_calls: list[ToolCall]
    step_count: int