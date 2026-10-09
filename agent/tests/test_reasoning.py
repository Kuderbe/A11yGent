"""Tests for reasoning-turn validation.

Offline, no NVDA/network. Reasoning may plan a future action in natural language,
but must not serialize a tool call as text.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_reasoning
"""

import asyncio

from a11y_gent.model.message import MessageOrigin
from a11y_gent.runtime.graph import think_node
from a11y_gent.runtime.reasoning import (
    ReasoningToolCallSyntaxError,
    assert_plain_text_reasoning,
)


def test_plain_text_reasoning_can_plan_a_report():
    assert_plain_text_reasoning(
        "NVDA announced only 'clickable', which confirms a barrier. "
        "Next action: report the confirmed barrier."
    )


def test_plain_text_reasoning_can_name_a_tool_without_call_syntax():
    assert_plain_text_reasoning(
        "The next action should use report_barrier with the observed evidence."
    )


def test_serialized_invoke_syntax_is_rejected():
    try:
        assert_plain_text_reasoning('<|channel| invoke name="report_barrier">')
    except ReasoningToolCallSyntaxError as error:
        assert "following act turn" in str(error)
    else:
        raise AssertionError("Expected serialized invoke syntax to be rejected")


def test_tool_call_markup_is_rejected():
    try:
        assert_plain_text_reasoning("<tool_call>report_barrier</tool_call>")
    except ReasoningToolCallSyntaxError:
        pass
    else:
        raise AssertionError("Expected tool-call markup to be rejected")


class _LeakingThinkLlm:
    async def infer(self, history, model, use_tools=True):
        assert use_tools is False
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": '<|channel| invoke name="report_barrier">',
            }
        }


def test_think_node_rejects_serialized_tool_call_before_appending_it():
    state = {
        "llm": _LeakingThinkLlm(),
        "task": {"url": "http://example.test", "goal": "Check the page."},
        "model": "m",
        "max_steps": 30,
        "discovery_context": [],
        "pending_tool_calls": [],
        "step_count": 0,
    }
    try:
        asyncio.run(think_node(state))
    except ReasoningToolCallSyntaxError:
        pass
    else:
        raise AssertionError("Expected think_node to reject serialized tool-call syntax")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()