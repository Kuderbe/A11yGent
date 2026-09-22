from typing import NotRequired, TypedDict

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import Message
from a11y_gent.model.task import Task
from a11y_gent.model.tool_call import ToolCall


class GraphState(TypedDict):
    llm: LlmClient
    task: Task

    discovery_context: list[Message]
    pending_tool_calls: NotRequired[list[ToolCall]]
    step_count: int