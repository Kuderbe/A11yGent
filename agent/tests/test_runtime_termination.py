"""Tests for shared message-history inspection.

Offline, no NVDA/network: builds tiny message histories and states by hand and
checks whether the latest assistant message calls a named tool.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_runtime_termination
"""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.runtime.termination import latest_message_calls


def _tool_call(name):
    return {"id": "1", "tool": {"name": name, "description": "", "tool_function": lambda: None}, "arguments": {}}


def _assistant_calling(name):
    return {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [_tool_call(name)],
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


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
