"""Tests for the trajectory serialiser (a11y_gent.trajectory.recorder).

Offline, no NVDA/network. Verify that a message history is classified into
think / action / observation roles and serialised to JSON Lines.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_trajectory
"""

import json
import os
import tempfile

from a11y_gent.model.message import MessageOrigin
from a11y_gent.trajectory.recorder import classify, to_records, write_jsonl


def _history():
    action_tool = {"name": "send_keys"}
    return [
        {"origin": MessageOrigin.SYSTEM, "name": "system", "content": "sys"},
        {"origin": MessageOrigin.USER, "name": "user", "content": "task"},
        {"origin": MessageOrigin.ASSISTANT, "name": "assistant",
         "content": "Thought: I will press b."},
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "tool": action_tool,
                    "arguments": {"gestures": ["b"]},
                }
            ],
        },
        {
            "origin": MessageOrigin.TOOL,
            "name": "send_keys",
            "content": "{\"ok\": true}",
            "reference_id": "call_1",
        },
    ]


def test_classify_roles():
    history = _history()
    assert classify(history[0]) == "system"
    assert classify(history[1]) == "user"
    assert classify(history[2]) == "think"
    assert classify(history[3]) == "action"
    assert classify(history[4]) == "observation"


def test_to_records_captures_tool_calls_and_reference():
    records = to_records(_history())
    action = records[3]
    assert action["role"] == "action"
    assert action["tool_calls"][0]["tool"] == "send_keys"
    assert action["tool_calls"][0]["arguments"] == {"gestures": ["b"]}

    observation = records[4]
    assert observation["role"] == "observation"
    assert observation["reference_id"] == "call_1"


def test_write_jsonl_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        write_jsonl(_history(), path)
        with open(path, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        assert len(lines) == 5
        assert [line["role"] for line in lines] == [
            "system",
            "user",
            "think",
            "action",
            "observation",
        ]
    finally:
        os.remove(path)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
