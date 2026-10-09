"""Validation for plain-text reasoning turns."""

import re


class ReasoningToolCallSyntaxError(RuntimeError):
    """Raised when a reasoning turn serializes a tool call as text."""


_SERIALIZED_TOOL_CALL = re.compile(
    r"<\|[^>\n]*\|\s*invoke\s+name\s*=|<tool_call(?:\s|>)|<function_call(?:\s|>)",
    re.IGNORECASE,
)


def assert_plain_text_reasoning(content: str) -> None:
    """Reject serialized tool-call syntax in a reasoning response."""
    if _SERIALIZED_TOOL_CALL.search(content):
        raise ReasoningToolCallSyntaxError(
            "Reasoning turns must not serialize tool calls; plan the action in plain text "
            "and make the real call in the following act turn."
        )