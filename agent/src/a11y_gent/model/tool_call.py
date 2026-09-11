from typing import Any, TypedDict

from a11y_gent.model.tool import Tool


class ToolCall(TypedDict):
    id: str
    tool: Tool
    arguments: dict[str, Any]