"""Checkpointed superstate for phased workflow execution."""

from operator import add
from typing import Annotated, TypedDict

from a11y_gent.model.message import Message
from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import BarrierEnrichment, Candidate, TaskResult, VerificationOutcome, WorkflowTask


class SolveTaskSubstate(TypedDict):
    """State retained for one solve-task attempt."""

    task: WorkflowTask
    history: list[Message]


class RetrospectiveSubstate(TypedDict):
    """State retained for one retrospective analysis."""

    task: WorkflowTask
    solve_task_history: list[Message]
    history: list[Message]
    candidates: list[Candidate]
    iterations: int


class VerificationSubstate(TypedDict):
    """State retained for one candidate verification."""

    task: WorkflowTask
    candidate_reference: int
    candidate: Candidate
    history: list[Message]
    outcome: VerificationOutcome


class EnrichmentSubstate(TypedDict):
    """State retained for one confirmed-barrier enrichment."""

    barrier_reference: int
    barrier: Barrier
    enrichment: BarrierEnrichment


class WorkflowRuntimeState(TypedDict):
    """State retained by the checkpointed workflow supergraph."""

    tasks: list[WorkflowTask]
    discovery_state: dict[str, object]
    solve_states: Annotated[list[SolveTaskSubstate], add]
    retrospective_states: Annotated[list[RetrospectiveSubstate], add]
    verification_states: Annotated[list[VerificationSubstate], add]
    final_result_states: Annotated[list[TaskResult], add]
    enrichment_states: Annotated[list[EnrichmentSubstate], add]