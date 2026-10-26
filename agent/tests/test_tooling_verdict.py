"""Tests for the report_verdict / report_barrier tools and extraction.

Offline, no NVDA/network. Verify that both no-op sink tools expose the expected
OpenAI schema and return their acknowledgements, and that extract_verdict /
extract_barriers rebuild the typed objects from a message history containing the
corresponding tool calls.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_tooling_verdict
"""

from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.extract import extract_barriers, extract_verdict
from a11y_gent.tooling.verdict import make_verdict_tool


def _assistant_call(tool_name, arguments, call_id="c1"):
    return {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [
            {"id": call_id, "tool": {"name": tool_name}, "arguments": arguments}
        ],
    }


def test_verdict_tool_is_noop_sink_with_expected_schema():
    tool = make_verdict_tool()
    assert tool["tool_function"](status="failed", summary="blocked") == (
        "verdict recorded"
    )

    conv = OpenaiLlmClient._convert_tool(tool)
    props = conv["function"]["parameters"]["properties"]
    required = conv["function"]["parameters"]["required"]
    assert conv["function"]["name"] == "report_verdict"
    assert props["status"]["type"] == "string"
    assert props["summary"]["type"] == "string"
    assert "barriers" not in props
    assert set(required) == {"status", "summary"}


def test_barrier_tool_is_noop_sink_with_expected_schema():
    tool = make_barrier_tool()
    assert tool["tool_function"](
        description="d",
        expected_behavior="expected",
        actual_behavior="actual",
        reproduction_steps=["step"],
        evidence="e",
    ) == (
        "barrier recorded"
    )

    conv = OpenaiLlmClient._convert_tool(tool)
    props = conv["function"]["parameters"]["properties"]
    required = conv["function"]["parameters"]["required"]
    assert conv["function"]["name"] == "report_barrier"
    assert props["description"]["type"] == "string"
    assert props["expected_behavior"]["type"] == "string"
    assert props["actual_behavior"]["type"] == "string"
    assert props["reproduction_steps"]["type"] == "array"
    assert props["evidence"]["type"] == "string"
    assert "wcag" not in props
    assert set(required) == {
        "description",
        "expected_behavior",
        "actual_behavior",
        "reproduction_steps",
        "evidence",
    }


def test_extract_barriers_from_history():
    history = [
        {"origin": MessageOrigin.SYSTEM, "name": "system", "content": "sys"},
        _assistant_call(
            "report_barrier",
            {
                "description": "no name",
                "expected_behavior": "A name is announced.",
                "actual_behavior": "No name is announced.",
                "reproduction_steps": ["Navigate to the control."],
                "evidence": "clickable",
            },
            "b1",
        ),
        _assistant_call(
            "report_barrier",
            {
                "description": "trap",
                "expected_behavior": "Focus can leave the control.",
                "actual_behavior": "Focus remains trapped.",
                "reproduction_steps": ["Open the dialog.", "Press Tab."],
                "evidence": "stuck",
            },
            "b2",
        ),
    ]
    barriers = extract_barriers(history)
    assert len(barriers) == 2
    assert barriers[0] == {
        "description": "no name",
        "expected_behavior": "A name is announced.",
        "actual_behavior": "No name is announced.",
        "reproduction_steps": ["Navigate to the control."],
        "evidence": "clickable",
    }
    assert barriers[1]["reproduction_steps"] == ["Open the dialog.", "Press Tab."]


def test_extract_verdict_uses_reported_barriers():
    history = [
        _assistant_call(
            "report_barrier",
            {
                "description": "no name",
                "expected_behavior": "A name is announced.",
                "actual_behavior": "No name is announced.",
                "reproduction_steps": ["Navigate to the control."],
                "evidence": "clickable",
            },
            "b1",
        ),
        _assistant_call(
            "report_verdict", {"status": "failed", "summary": "blocked"}, "v1"
        ),
    ]
    verdict = extract_verdict(history)
    assert verdict is not None
    assert verdict["status"] is VerdictStatus.FAILED
    assert verdict["summary"] == "blocked"
    assert len(verdict["barriers"]) == 1
    assert verdict["barriers"][0]["description"] == "no name"


def test_extract_verdict_none_when_not_reported():
    history = [
        {"origin": MessageOrigin.ASSISTANT, "name": "assistant",
         "content": "Thought: still working."},
    ]
    assert extract_verdict(history) is None


def test_extract_verdict_bad_status_falls_back_to_failed():
    history = [
        _assistant_call(
            "report_verdict", {"status": "weird", "summary": "?"}, "v1"
        ),
    ]
    assert extract_verdict(history)["status"] is VerdictStatus.FAILED


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
