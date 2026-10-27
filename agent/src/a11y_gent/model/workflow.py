"""Domain representations shared by phases of the task-assessment workflow."""

from dataclasses import dataclass
from enum import Enum
from typing import NotRequired, TypedDict

from a11y_gent.model.verdict import Barrier, Verdict


class WorkflowPhase(Enum):
    """A stage in the task-assessment workflow."""

    DISCOVERY = "discovery"
    SOLVE_TASK = "solve_task"
    RETROSPECTIVE = "retrospective"
    VERIFY = "verify"
    GATHER_INFO_FOR_REPORT = "gather_info_for_report"
    WRITE_REPORT = "write_report"

    def __str__(self) -> str:
        return self.value


class WorkflowTask(TypedDict):
    """One numbered task selected for assessment."""

    number: int
    url: str
    description: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Tasks found during discovery and whether its inventory is incomplete."""

    tasks: list[WorkflowTask]
    incomplete: bool


class Candidate(TypedDict):
    """An unverified condition that retrospective analysis requests to verify."""

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


class TaskResult(TypedDict):
    """The final task verdict derived from completed workflow phases."""

    task: WorkflowTask
    verdict: Verdict


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