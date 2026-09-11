from typing import Callable, TypedDict


class Tool(TypedDict):
    description: str
    name: str
    tool_function: Callable