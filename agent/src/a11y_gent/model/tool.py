from typing import Callable, TypedDict


class Tool(TypedDict):
    description: str
    name: str
    tool_function: Callable


class SerializedTool(TypedDict):
    """The serializable identity of a tool retained in message history."""

    description: str
    name: str