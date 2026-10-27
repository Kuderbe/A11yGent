"""Offline tests for deterministic per-task Markdown rendering."""

from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.report_rendering import render_task_markdown_sections


def test_renders_a_task_outcome_and_enriched_confirmed_barrier_details():
    markdown = render_task_markdown_sections(
        [_task_result()],
        [],
        [_enrichment_state()],
        [],
    )

    assert markdown == """## Task 01: Complete checkout

- **URL:** https://shop.example/checkout
- **Outcome:** succeeded with avoidable difficulty — Checkout completed.

### Confirmed barriers

#### Unnamed payment button

- **Description:** The payment button has no accessible name.
- **Expected behavior:** NVDA announces the payment button.
- **Actual behavior:** NVDA announces only button.
- **Implementation context:** The button has no accessible name.
- **Steps to reproduce:**
  1. Navigate to payment.
- **Suggested fix:** Provide an accessible name.
- **Evidence:** Speech: button.
- **Provenance:** Task 01

### Unverified candidates

None.

### Execution errors

None.

## Scope caveat

This assessment covers the listed tasks with an NVDA screen-reader profile in newly opened browser windows. It is not a complete accessibility audit or certification; browser-profile state may persist between task windows.
"""


def test_renders_unverified_candidates_and_execution_errors_separately():
    markdown = render_task_markdown_sections(
        [_task_result(barriers=[])],
        [
            {
                "task": _task_result()["task"],
                "candidate_reference": 0,
                "candidate": {"description": "Confirmation may not be announced.", "verification_brief": "Submit the order."},
                "history": [],
                "outcome": {
                    "candidate_reference": 0,
                    "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
                    "evidence": "The NVDA interaction limit was reached.",
                },
            }
        ],
        [],
        [{"task_number": 1, "phase": "verify", "candidate_reference": 0, "message": "NVDA MCP stopped responding."}],
    )

    assert "### Confirmed barriers\n\nNone." in markdown
    assert "#### Candidate 1: Confirmation may not be announced." in markdown
    assert "- **Status:** unverified: budget exhausted" in markdown
    assert "- **Runtime reference:** 0" in markdown
    assert "### Execution errors\n\n- **Verify (candidate 1):** NVDA MCP stopped responding." in markdown


def test_renders_maximum_step_failures_and_enrichment_errors():
    result = _task_result()
    result["verdict"] = {
        "status": VerdictStatus.FAILED,
        "summary": "The maximum NVDA interaction limit was reached.",
        "barriers": [_barrier()],
    }
    fallback = _enrichment_state()
    fallback["enrichment"] = {
        "title": "The payment button has no accessible name.",
        "implementation_context": "",
        "remediation_target": "",
        "suggested_fix": "manual investigation",
        "error": "DevTools inspection timed out",
    }

    markdown = render_task_markdown_sections([result], [], [fallback], [])

    assert "- **Outcome:** failed — The maximum NVDA interaction limit was reached." in markdown
    assert "- **Suggested fix:** manual investigation" in markdown
    assert "- **Enrichment error:** DevTools inspection timed out" in markdown


def test_matches_enrichment_to_the_global_barrier_order_across_tasks():
    first = _task_result()
    second = _task_result()
    second["task"] = {"number": 2, "url": "https://shop.example/account", "description": "Manage account"}
    second["verdict"]["barriers"] = [_account_barrier()]
    second_enrichment = _enrichment_state()
    second_enrichment["barrier_reference"] = 1
    second_enrichment["barrier"] = _account_barrier()
    second_enrichment["enrichment"]["title"] = "Unnamed account button"

    markdown = render_task_markdown_sections([first, second], [], [_enrichment_state(), second_enrichment], [])

    assert "## Task 02: Manage account\n\n- **URL:** https://shop.example/account" in markdown
    assert "## Task 02: Manage account" in markdown
    assert "#### Unnamed account button" in markdown


def _task_result(barriers=None):
    return {
        "task": {"number": 1, "url": "https://shop.example/checkout", "description": "Complete checkout"},
        "verdict": {
            "status": VerdictStatus.SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY,
            "summary": "Checkout completed.",
            "barriers": [_barrier()] if barriers is None else barriers,
        },
    }


def _barrier():
    return {
        "description": "The payment button has no accessible name.",
        "expected_behavior": "NVDA announces the payment button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to payment."],
        "evidence": "Speech: button.",
    }


def _account_barrier():
    return {
        "description": "The account button has no accessible name.",
        "expected_behavior": "NVDA announces the account button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to account."],
        "evidence": "Speech: button.",
    }


def _enrichment_state():
    return {
        "barrier_reference": 0,
        "barrier": _barrier(),
        "enrichment": {
            "title": "Unnamed payment button",
            "implementation_context": "The button has no accessible name.",
            "remediation_target": "Payment button",
            "suggested_fix": "Provide an accessible name.",
        },
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()