"""Domain representations shared by phases of the task-assessment workflow."""

from enum import Enum
from typing import NotRequired, TypedDict

from a11y_gent.model.verdict import Barrier


class WorkflowTask(TypedDict):
    """One numbered task selected for assessment."""

    number: int
    url: str
    description: str


class Candidate(TypedDict):
    """An unverified condition that retrospective analysis requests to verify."""

    reference: int
    task_number: int
    description: str
    verification_brief: str


class VerificationOutcomeStatus(Enum):
    """The conclusion of verifying one retrospective candidate."""

    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    UNVERIFIED_BUDGET_EXHAUSTED = "unverified_budget_exhausted"
    UNVERIFIED_EXECUTION_ERROR = "unverified_execution_error"

    def __str__(self) -> str:
        return self.value


class ExecutionError(TypedDict):
    """A phase failure that prevents normal task or candidate processing."""

    task_number: int
    phase: str
    message: str
    candidate_reference: NotRequired[int]


class VerificationOutcome(TypedDict):
    """The recorded conclusion of verifying one candidate."""

    candidate_reference: int
    status: VerificationOutcomeStatus
    evidence: str
    confirmed_barrier: NotRequired[Barrier]
    execution_error: NotRequired[ExecutionError]


class BarrierEnrichment(TypedDict):
    """Developer-oriented context for one confirmed barrier."""

    title: str
    implementation_context: str
    remediation_target: str
    suggested_fix: str
    error: NotRequired[str]


class AggregateBarrier(TypedDict):
    """Confirmed barrier occurrences with one shared remediation."""

    title: str
    barrier_references: list[int]
    remediation: str


class ReportInput(TypedDict):
    """All phase outputs consumed by deterministic report rendering."""

    tasks: list[WorkflowTask]
    confirmed_barriers: list[Barrier]
    unverified_candidates: list[VerificationOutcome]
    execution_errors: list[ExecutionError]
    enrichments: list[BarrierEnrichment]
    aggregates: list[AggregateBarrier]