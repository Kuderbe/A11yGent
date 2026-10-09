"""Tests for prompt assembly (a11y_gent.prompts).

Offline, no NVDA/network. Verify the system prompt embeds the task and the
success hint when present, and that the few-shot exemplars form a valid,
tool-call-free message list (they illustrate the reason-then-act format).

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_prompts
"""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.prompts import build_system_prompt, few_shot_exemplars


def test_system_prompt_embeds_task():
    prompt = build_system_prompt(
        {"url": "http://example.test/x", "goal": "Sign up for an account."}
    )
    assert "http://example.test/x" in prompt
    assert "Sign up for an account." in prompt
    assert "report_verdict" in prompt
    assert "report_barrier" in prompt
    assert "Never imitate or serialize a tool call" in prompt
    assert "following action turn" in prompt
    # The three verdict statuses must be described to the model.
    assert "succeeded_with_avoidable_difficulty" in prompt
    # No success hint given -> the hint block is absent.
    assert "Success looks like" not in prompt


def test_system_prompt_includes_success_hint_when_present():
    prompt = build_system_prompt(
        {
            "url": "http://example.test/y",
            "goal": "Buy the first product.",
            "success_hint": "Order confirmation is announced.",
        }
    )
    assert "Success looks like: Order confirmation is announced." in prompt


def test_exemplars_are_valid_messages_without_tool_calls():
    exemplars = few_shot_exemplars()
    assert len(exemplars) >= 2
    for message in exemplars:
        assert isinstance(message["origin"], MessageOrigin)
        assert message["content"]
        assert message["name"]
        # Exemplars are narrated text only; no real tool calls are embedded.
        assert "tool_calls" not in message
    # At least one exemplar demonstrates a reasoning ("Thought:") turn.
    assert any("Thought:" in m["content"] for m in exemplars)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
