"""Offline tests for deterministic per-task Markdown rendering."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.report_rendering import render_markdown_report, render_task_markdown_sections, write_markdown_report


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


def test_renders_global_confirmed_numbers_and_discovery_disclosure():
    first = _task_result()
    second = _task_result()
    second["task"] = {"number": 2, "url": "https://shop.example/account", "description": "Manage account"}
    second["verdict"]["barriers"] = [_account_barrier()]
    second_enrichment = _enrichment_state()
    second_enrichment["barrier_reference"] = 1
    second_enrichment["barrier"] = _account_barrier()
    second_enrichment["enrichment"]["title"] = "Unnamed account button"

    markdown = render_markdown_report(
        [first, second], [], [_enrichment_state(), second_enrichment], True, discovery_max_steps=12, nvda_max_steps=34
    )

    assert markdown.startswith("# Accessibility assessment report\n\n- **Discovery:** Incomplete; tested tasks may not cover all ordinary-user goals.\n- **Limits:** 12 DevTools interactions; 34 NVDA interactions per task attempt and candidate verification.\n")
    assert "#### Barrier 1: Unnamed payment button" in markdown
    assert "#### Barrier 2: Unnamed account button" in markdown


def test_renders_gap_free_global_candidate_numbers_and_common_remediations():
    first = _task_result()
    second = _task_result()
    second["task"] = {"number": 2, "url": "https://shop.example/account", "description": "Manage account"}
    second["verdict"]["barriers"] = [_account_barrier()]
    second_enrichment = _enrichment_state()
    second_enrichment["barrier_reference"] = 1
    second_enrichment["barrier"] = _account_barrier()
    verification_states = [_unverified_state(first["task"], 3, "Payment confirmation may not be announced."), _unverified_state(second["task"], 0, "Account update may not be announced.")]

    markdown = render_markdown_report(
        [first, second], verification_states, [_enrichment_state(), second_enrichment], False, discovery_max_steps=12, nvda_max_steps=34
    )

    assert "#### Candidate 1: Payment confirmation may not be announced." in markdown
    assert "#### Candidate 2: Account update may not be announced." in markdown
    assert "## Common remediations\n\n### Unnamed payment button\n\n- **Barriers:** 1, 2\n- **Suggested fix:** Provide an accessible name." in markdown


def test_uses_global_candidate_numbers_in_execution_errors():
    first = _task_result(barriers=[])
    second = _task_result(barriers=[])
    second["task"] = {"number": 2, "url": "https://shop.example/account", "description": "Manage account"}
    first_verification = _unverified_state(first["task"], 3, "Payment confirmation may not be announced.")
    second_verification = _unverified_state(second["task"], 0, "Account update may not be announced.")
    second_verification["outcome"] = {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR,
        "evidence": "NVDA MCP stopped responding.",
        "execution_error": {"task_number": 2, "phase": "verify", "candidate_reference": 0, "message": "NVDA MCP stopped responding."},
    }

    markdown = render_markdown_report([first, second], [first_verification, second_verification], [], False, discovery_max_steps=12, nvda_max_steps=34)

    assert "## Task 02: Manage account" in markdown
    assert "### Execution errors\n\n- **Verify (candidate 2):** NVDA MCP stopped responding." in markdown


def test_discloses_no_confirmed_barriers_and_writes_requested_or_default_paths():
    markdown = render_markdown_report([_task_result(barriers=[])], [], [], False, discovery_max_steps=12, nvda_max_steps=34)

    assert "## No confirmed barriers\n\nNo confirmed barriers were found in the tested tasks." in markdown
    assert "- **Tested tasks:** 01 Complete checkout" in markdown
    with tempfile.TemporaryDirectory() as tmp:
        explicit = Path(tmp) / "reports" / "assessment.md"
        assert write_markdown_report(markdown, str(explicit)) == explicit
        assert explicit.read_text(encoding="utf-8") == markdown
        default = write_markdown_report(markdown, None, now=datetime(2026, 10, 27, 9, 45, tzinfo=UTC), directory=tmp)
        assert default == Path(tmp) / "a11y-report-2026-10-27T09-45-00Z.md"
        assert default.read_text(encoding="utf-8") == markdown


def test_derives_verification_execution_errors_for_the_complete_report():
    verification = _unverified_state(_task_result()["task"], 0, "Confirmation may not be announced.")
    verification["outcome"] = {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR,
        "evidence": "NVDA MCP stopped responding.",
        "execution_error": {"task_number": 1, "phase": "verify", "candidate_reference": 0, "message": "NVDA MCP stopped responding."},
    }

    markdown = render_markdown_report([_task_result(barriers=[])], [verification], [], False, discovery_max_steps=12, nvda_max_steps=34)

    assert "### Execution errors\n\n- **Verify (candidate 1):** NVDA MCP stopped responding." in markdown


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


def _unverified_state(task, candidate_reference, description):
    return {
        "task": task,
        "candidate_reference": candidate_reference,
        "candidate": {"description": description, "verification_brief": "Check with NVDA."},
        "history": [],
        "outcome": {
            "candidate_reference": candidate_reference,
            "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
            "evidence": "The NVDA interaction limit was reached.",
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