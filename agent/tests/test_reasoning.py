"""Tests for reasoning-turn history handling.

Offline, no NVDA/network. Reasoning text remains in history while only native
Action calls can execute tools.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_reasoning
"""

import asyncio

from a11y_gent.model.message import MessageOrigin
from a11y_gent.profiles.baseline.graph import think_node


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


def test_think_node_retains_serialized_tool_call_text_without_executing_it():
    state = {
        "llm": _LeakingThinkLlm(),
        "task": {"url": "http://example.test", "goal": "Check the page."},
        "model": "m",
        "max_steps": 30,
        "discovery_context": [],
        "pending_tool_calls": [],
        "step_count": 0,
    }
    result = asyncio.run(think_node(state))

    assert result["step_count"] == 1
    assert result["discovery_context"][-1]["content"] == '<|channel| invoke name="report_barrier">'


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()