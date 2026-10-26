"""Checkpointed state and provenance for phased workflow execution."""

from typing import TypedDict


class WorkflowProvenance(TypedDict):
    """One chronologically recorded workflow phase update."""

    run_id: str
    phase: str
    task_number: int | None
    candidate_reference: int | None


class WorkflowRuntimeState(TypedDict):
    """State persisted by the workflow checkpointer."""

    phase_contexts: dict[str, object]
    pending_phase: str
    pending_context: object
    pending_task_number: int | None
    pending_candidate_reference: int | None