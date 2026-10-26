"""Offline tests for phased workflow domain representations.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_workflow_model
"""

from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import (
    AggregateBarrier,
    BarrierEnrichment,
    Candidate,
    ExecutionError,
    ReportInput,
    VerificationOutcome,
    VerificationOutcomeStatus,
    WorkflowTask,
)


def test_confirmed_barrier_has_actionable_observed_fields():
    barrier: Barrier = {
        "description": "The shipping option is not announced.",
        "expected_behavior": "NVDA announces each shipping option and its state.",
        "actual_behavior": "NVDA announces an unlabeled control.",
        "reproduction_steps": ["Open checkout.", "Navigate to shipping options."],
        "evidence": "Speech: unlabeled button",
    }

    assert barrier["expected_behavior"] == "NVDA announces each shipping option and its state."
    assert barrier["reproduction_steps"] == ["Open checkout.", "Navigate to shipping options."]


def test_candidate_and_outcome_status_distinguish_unverified_reasons():
    candidate: Candidate = {
        "reference": 4,
        "task_number": 2,
        "description": "Error feedback may not be announced.",
        "verification_brief": "Submit the empty form and inspect the feedback.",
    }

    assert candidate["reference"] == 4
    assert VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED.value == "unverified_budget_exhausted"
    assert VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR.value == "unverified_execution_error"


def test_verification_outcome_carries_the_evidence_for_its_conclusion():
    outcome: VerificationOutcome = {
        "candidate_reference": 4,
        "status": VerificationOutcomeStatus.DISCARDED,
        "evidence": "The feedback is announced after submission.",
    }

    assert outcome["candidate_reference"] == 4
    assert outcome["status"] is VerificationOutcomeStatus.DISCARDED
    assert outcome["evidence"] == "The feedback is announced after submission."


def test_report_input_keeps_findings_candidates_and_errors_separate():
    task: WorkflowTask = {
        "number": 2,
        "url": "https://shop.example/checkout",
        "description": "Choose a shipping option.",
    }
    barrier: Barrier = {
        "description": "The shipping option is not announced.",
        "expected_behavior": "NVDA announces each shipping option and its state.",
        "actual_behavior": "NVDA announces an unlabeled control.",
        "reproduction_steps": ["Open checkout.", "Navigate to shipping options."],
        "evidence": "Speech: unlabeled button",
    }
    enrichment: BarrierEnrichment = {
        "title": "Unnamed shipping option",
        "implementation_context": "The control has no accessible name.",
        "remediation_target": "Shipping option control",
        "suggested_fix": "Provide an accessible name.",
    }
    error: ExecutionError = {
        "task_number": 2,
        "phase": "verify",
        "message": "The browser window could not be opened.",
    }
    aggregate: AggregateBarrier = {
        "title": "Unnamed shipping option",
        "barrier_references": [1],
        "remediation": "Provide an accessible name.",
    }
    report: ReportInput = {
        "tasks": [task],
        "confirmed_barriers": [barrier],
        "unverified_candidates": [
            {
                "candidate_reference": 4,
                "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
                "evidence": "The NVDA interaction limit was reached.",
            }
        ],
        "execution_errors": [error],
        "enrichments": [enrichment],
        "aggregates": [aggregate],
    }

    assert report["confirmed_barriers"] == [barrier]
    assert report["unverified_candidates"][0]["status"] is VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED
    assert report["execution_errors"] == [error]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()