"""Offline contracts for the complete assessment report object."""

import tempfile
from pathlib import Path

from a11y_gent.model.assessment_report import AssessmentReport
from a11y_gent.model.verdict import VerdictStatus


def test_report_renders_workflow_outputs_and_saves_markdown():
    report = AssessmentReport.from_workflow_state(
        {
            "tasks": [_task()],
            "discovery_state": {"incomplete": False},
            "solve_states": [],
            "retrospective_states": [],
            "verification_states": [],
            "final_result_states": [{"task": _task(), "verdict": _verdict()}],
            "enrichment_states": [_enrichment_state()],
        },
        discovery_max_steps=12,
        nvda_max_steps=34,
    )

    assert "# Accessibility assessment report" in report.to_markdown()
    assert "#### Barrier 1: Unnamed payment button" in report.to_markdown()
    with tempfile.TemporaryDirectory() as tmp:
        path = report.save_to_file(Path(tmp) / "assessment.md")
        assert path.read_text(encoding="utf-8") == report.to_markdown()


def test_report_retains_its_phase_outputs_and_discovery_disclosure():
    report = AssessmentReport.from_workflow_state(
        {
            "tasks": [_task()],
            "discovery_state": {"incomplete": True},
            "solve_states": [],
            "retrospective_states": [],
            "verification_states": [],
            "final_result_states": [{"task": _task(), "verdict": _verdict()}],
            "enrichment_states": [_enrichment_state()],
        },
        discovery_max_steps=12,
        nvda_max_steps=34,
    )

    assert report.final_results[0]["verdict"] == _verdict()
    assert report.enrichment_states == [_enrichment_state()]
    assert report.discovery_incomplete is True
    assert report.execution_errors == []
    assert report.aggregates == []
    assert "**Discovery:** Incomplete" in report.to_markdown()


def _task():
    return {"number": 1, "url": "https://shop.example/", "description": "Complete checkout"}


def _verdict():
    return {
        "status": VerdictStatus.SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY,
        "summary": "Checkout completed.",
        "barriers": [
            {
                "description": "The payment button has no accessible name.",
                "expected_behavior": "NVDA announces the payment button.",
                "actual_behavior": "NVDA announces only button.",
                "reproduction_steps": ["Navigate to payment."],
                "evidence": "Speech: button.",
            }
        ],
    }


def _enrichment_state():
    return {
        "barrier_reference": 0,
        "barrier": _verdict()["barriers"][0],
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