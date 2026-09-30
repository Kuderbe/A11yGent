"""Tests for the loop termination logic (a11y_gent.runtime.termination).

Offline, no NVDA/network: builds tiny message histories and states by hand and
checks that should_continue stops on a report_verdict in the latest message or
when the step cap is reached, and continues otherwise.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_runtime_termination
"""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.runtime.termination import latest_message_calls, should_continue


def _tool_call(name):
    return {"id": "1", "tool": {"name": name, "description": "", "tool_function": lambda: None}, "arguments": {}}


def _assistant_calling(name):
    return {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [_tool_call(name)],
    }


def _thought():
    return {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "thinking"}


def _state(history, step_count=0, max_steps=30):
    return {
        "llm": None,
        "task": {"url": "u", "goal": "g"},
        "model": "m",
        "max_steps": max_steps,
        "discovery_context": history,
        "pending_tool_calls": [],
        "step_count": step_count,
    }


def test_latest_message_calls_true_for_matching_last_call():
    history = [_assistant_calling("report_verdict")]
    assert latest_message_calls(history, "report_verdict") is True


def test_latest_message_calls_false_for_empty_history():
    assert latest_message_calls([], "report_verdict") is False


def test_latest_message_calls_false_when_last_is_not_assistant():
    history = [
        _assistant_calling("report_verdict"),
        {"origin": MessageOrigin.TOOL, "name": "report_verdict", "content": "ok", "reference_id": "1"},
    ]
    assert latest_message_calls(history, "report_verdict") is False


def test_should_continue_done_on_verdict():
    state = _state([_assistant_calling("report_verdict")])
    assert should_continue(state) == "done"


def test_should_continue_done_on_step_cap():
    state = _state([_thought()], step_count=30, max_steps=30)
    assert should_continue(state) == "done"


def test_should_continue_tools_otherwise():
    state = _state([_assistant_calling("report_barrier")], step_count=3, max_steps=30)
    assert should_continue(state) == "tools"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
