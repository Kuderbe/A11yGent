"""Derive final task verdicts from completed workflow phase state."""

from collections.abc import Iterable

from a11y_gent.model.message import Message
from a11y_gent.model.verdict import Barrier, Verdict, VerdictStatus
from a11y_gent.model.workflow import TaskResult, VerificationOutcome, VerificationOutcomeStatus, WorkflowTask
from a11y_gent.tooling.extract import extract_barriers


def derive_task_result(
    task: WorkflowTask, solve_task_history: Iterable[Message], verification_outcomes: Iterable[VerificationOutcome]
) -> TaskResult:
    """Derive one final task result from solve-task and verification evidence."""
    solve_task_history = list(solve_task_history)
    barriers = [
        *extract_barriers(solve_task_history),
        *(_confirmed_barrier(outcome) for outcome in verification_outcomes if outcome["status"] is VerificationOutcomeStatus.CONFIRMED),
    ]
    completion = _solve_task_completion(solve_task_history)
    if completion is None or completion["status"] is VerdictStatus.FAILED:
        return {"task": task, "verdict": {"status": VerdictStatus.FAILED, "summary": _summary(completion), "barriers": barriers}}
    status = VerdictStatus.SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY if barriers else VerdictStatus.SUCCEEDED
    return {"task": task, "verdict": {"status": status, "summary": completion["summary"], "barriers": barriers}}


def _confirmed_barrier(outcome: VerificationOutcome) -> Barrier:
    return outcome["confirmed_barrier"]


def _solve_task_completion(history: Iterable[Message]) -> dict[str, object] | None:
    for message in reversed(list(history)):
        for call in reversed(message.get("tool_calls", [])):
            if call["tool"]["name"] == "complete_solve_task":
                return {"status": _status(call["arguments"].get("status")), "summary": str(call["arguments"].get("summary", ""))}
    return None


def _status(value: object) -> VerdictStatus:
    try:
        return VerdictStatus(str(value))
    except ValueError:
        return VerdictStatus.FAILED


def _summary(completion: dict[str, object] | None) -> str:
    if completion is None:
        return "The solve-task attempt did not complete."
    return str(completion["summary"])