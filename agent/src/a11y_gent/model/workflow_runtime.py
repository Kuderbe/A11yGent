"""Checkpointed superstate for phased workflow execution."""

from typing import TypedDict

from a11y_gent.model.message import Message
from a11y_gent.model.workflow import Candidate, WorkflowTask


class SolveTaskSubstate(TypedDict):
    """Durable solve-task output owned by one task pipeline."""

    history: list[Message]


class RetrospectiveSubstate(TypedDict):
    """Durable retrospective output owned by one task pipeline."""

    history: list[Message]
    candidates: list[Candidate]


class TaskPipelineState(TypedDict):
    """All phase substates for one selected task."""

    task: WorkflowTask
    solve_task_state: SolveTaskSubstate
    retrospective_state: RetrospectiveSubstate
    verification_state: dict[str, object]
    final_result_state: dict[str, object]


class WorkflowRuntimeState(TypedDict):
    """State retained by the checkpointed workflow supergraph."""

    task_pipelines: list[TaskPipelineState]