"""Offline contracts for deterministic final task-result derivation."""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.task_results import derive_task_result


def test_derive_task_result_keeps_a_failed_solve_task_failed():
    result = derive_task_result(_task(), _solve_history("failed"), [_confirmed_verification()])

    assert result["verdict"]["status"] is VerdictStatus.FAILED
    assert result["verdict"]["summary"] == "Checkout could not be completed."
    assert result["verdict"]["barriers"] == [_direct_barrier(), _confirmed_barrier()]


def test_derive_task_result_marks_a_completed_task_with_confirmed_barriers_avoidable():
    result = derive_task_result(_task(), _solve_history("succeeded"), [_confirmed_verification()])

    assert result["verdict"]["status"] is VerdictStatus.SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY
    assert result["verdict"]["barriers"] == [_direct_barrier(), _confirmed_barrier()]


def test_derive_task_result_ignores_unverified_and_discarded_candidates():
    result = derive_task_result(_task(), _solve_history("succeeded"), [_discarded_verification(), _unverified_verification()])

    assert result["verdict"] == {
        "status": VerdictStatus.SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY,
        "summary": "Checkout completed.",
        "barriers": [_direct_barrier()],
    }


def test_derive_task_result_succeeds_without_confirmed_barriers():
    result = derive_task_result(_task(), _solve_history("succeeded", barriers=[]), [_discarded_verification()])

    assert result["verdict"] == {
        "status": VerdictStatus.SUCCEEDED,
        "summary": "Checkout completed.",
        "barriers": [],
    }


def test_derive_task_result_ignores_an_unverified_candidate_without_barriers():
    result = derive_task_result(_task(), _solve_history("succeeded", barriers=[]), [_unverified_verification()])

    assert result["verdict"] == {
        "status": VerdictStatus.SUCCEEDED,
        "summary": "Checkout completed.",
        "barriers": [],
    }


def _task():
    return {"number": 1, "url": "https://shop.example/", "description": "Complete checkout."}


def _solve_history(status, summary=None, barriers=None):
    summary = summary or ("Checkout completed." if status == "succeeded" else "Checkout could not be completed.")
    return [
        *[_barrier_message(barrier) for barrier in (_direct_barrier(),) if barriers is None],
        _completion_message(status, summary),
    ]


def _barrier_message(barrier):
    return {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [{"id": "direct", "tool": {"name": "report_barrier", "description": ""}, "arguments": barrier}],
    }


def _completion_message(status, summary):
    return {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "complete",
                "tool": {"name": "complete_solve_task", "description": ""},
                "arguments": {"status": status, "summary": summary},
            }
        ],
    }


def _confirmed_verification():
    return {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.CONFIRMED,
        "evidence": "NVDA did not announce the order confirmation.",
        "confirmed_barrier": _confirmed_barrier(),
    }


def _discarded_verification():
    return {
        "candidate_reference": 1,
        "status": VerificationOutcomeStatus.DISCARDED,
        "evidence": "NVDA announced the validation error.",
    }


def _unverified_verification():
    return {
        "candidate_reference": 2,
        "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
        "evidence": "The NVDA interaction limit was reached.",
    }


def _direct_barrier():
    return {
        "description": "The payment button has no accessible name.",
        "expected_behavior": "NVDA announces the payment button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to payment."],
        "evidence": "Speech: button.",
    }


def _confirmed_barrier():
    return {
        "description": "The order confirmation is not announced.",
        "expected_behavior": "NVDA announces the confirmation.",
        "actual_behavior": "No confirmation is announced.",
        "reproduction_steps": ["Submit the order."],
        "evidence": "Speech remains on the submit button.",
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()