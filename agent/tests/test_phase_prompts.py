"""Offline contracts for phased-workflow prompts."""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.prompts import (
    build_discovery_prompt,
    build_report_enrichment_prompt,
    build_retrospective_prompt,
    build_solve_task_prompt,
    build_verify_prompt,
    make_discovery_completion_tool,
    make_report_enrichment_completion_tool,
    make_retrospective_completion_tool,
    make_solve_task_completion_tool,
    make_verify_completion_tool,
)


def test_discovery_prompt_requests_numbered_tasks_without_findings():
    prompt = build_discovery_prompt(
        "https://shop.example/",
        "Use the supplied demo account and focus on checkout.",
    )

    assert "https://shop.example/" in prompt
    assert "Use the supplied demo account and focus on checkout." in prompt
    assert "numbered" in prompt
    assert "ordinary-user tasks" in prompt
    assert "Do not make accessibility findings" in prompt


def test_discovery_completion_contract_returns_task_descriptions_only():
    tool = make_discovery_completion_tool()

    assert tool["name"] == "complete_discovery"
    assert tool["tool_function"](
        task_descriptions=["Add a product to the cart."], incomplete=False
    ) == "discovery completed"
    assert _schema_properties(tool) == {"task_descriptions", "incomplete"}


def test_solve_task_prompt_uses_only_the_task_and_reports_observed_barriers():
    prompt = build_solve_task_prompt(_task())

    assert "Purchase the first product." in prompt
    assert "https://shop.example/" in prompt
    assert "NVDA" in prompt
    assert "report_barrier" in prompt
    assert "description" in prompt
    assert "expected behavior" in prompt
    assert "actual behavior" in prompt
    assert "executed reproduction steps" in prompt
    assert "evidence" in prompt
    assert "complete_solve_task" in prompt
    assert "DevTools" not in prompt

    tool = make_solve_task_completion_tool()
    assert tool["tool_function"](status="succeeded", summary="Order confirmed.") == "solve task completed"
    assert _schema_properties(tool) == {"status", "summary"}


def test_retrospective_prompt_uses_immutable_solve_history_for_candidates_only():
    history = [
        *_solve_history(),
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "barrier-1",
                    "tool": {"name": "report_barrier", "description": ""},
                    "arguments": {"description": "Submit button has no name."},
                }
            ],
        },
    ]
    prompt = build_retrospective_prompt(_task(), history)

    assert "Purchase the first product." in prompt
    assert "Submit button announced" in prompt
    assert "report_barrier" in prompt
    assert "Submit button has no name." in prompt
    assert "candidates" in prompt
    assert "Do not report a confirmed barrier" in prompt

    tool = make_retrospective_completion_tool()
    assert tool["tool_function"](
        descriptions=["The confirmation may not be announced."],
        verification_briefs=["Submit and inspect NVDA speech."],
    ) == "retrospective completed"
    assert _schema_properties(tool) == {"descriptions", "verification_briefs"}


def test_verify_prompt_receives_only_task_candidate_and_brief():
    prompt = build_verify_prompt(
        _task(),
        4,
        {
            "description": "The confirmation may not be announced.",
            "verification_brief": "Submit and inspect NVDA speech.",
        },
    )

    assert "Purchase the first product." in prompt
    assert "The confirmation may not be announced." in prompt
    assert "Submit and inspect NVDA speech." in prompt
    assert "NVDA" in prompt
    assert "DevTools" not in prompt

    tool = make_verify_completion_tool()
    assert tool["tool_function"](
        status="confirmed",
        evidence="Speech: no confirmation after submission.",
        description="The confirmation is not announced.",
        expected_behavior="NVDA announces the confirmation.",
        actual_behavior="NVDA announces no confirmation.",
        reproduction_steps=["Submit the form."],
    ) == "verification completed"
    assert _schema_properties(tool) == {
        "status",
        "evidence",
        "description",
        "expected_behavior",
        "actual_behavior",
        "reproduction_steps",
    }


def test_report_enrichment_prompt_cannot_change_the_confirmed_barrier():
    prompt = build_report_enrichment_prompt(_barrier())

    assert "Submit button has no name." in prompt
    assert "implementation context" in prompt
    assert "Do not alter the confirmed barrier" in prompt

    tool = make_report_enrichment_completion_tool()
    assert tool["tool_function"](
        title="Unnamed submit button",
        implementation_context="The button has no accessible name.",
        remediation_target="Submit button",
        suggested_fix="Provide an accessible name.",
    ) == "report enrichment completed"
    assert _schema_properties(tool) == {
        "title",
        "implementation_context",
        "remediation_target",
        "suggested_fix",
    }


def _task():
    return {"number": 1, "url": "https://shop.example/", "description": "Purchase the first product."}


def _solve_history():
    return [
        {
            "origin": MessageOrigin.TOOL,
            "name": "read_speech",
            "content": "Submit button announced without a name.",
            "reference_id": "call-1",
        }
    ]


def _barrier():
    return {
        "description": "Submit button has no name.",
        "expected_behavior": "NVDA announces the submit button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to the submit button."],
        "evidence": "Speech: button.",
    }


def _schema_properties(tool):
    schema = OpenaiLlmClient._convert_tool(tool)
    return set(schema["function"]["parameters"]["properties"])


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()