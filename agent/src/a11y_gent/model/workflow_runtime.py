"""Checkpointed superstate for phased workflow execution."""

from typing import Annotated, TypedDict

from a11y_gent.model.message import Message
from a11y_gent.model.workflow import Candidate, WorkflowTask


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


def replace_retrospective_states(
    current: list[RetrospectiveSubstate], updates: list[RetrospectiveSubstate]
) -> list[RetrospectiveSubstate]:
    """Replace updated retrospective states by their task number."""
    if not current:
        return updates
    updates_by_number = {state["task"]["number"]: state for state in updates}
    return [updates_by_number.get(state["task"]["number"], state) for state in current]


class WorkflowRuntimeState(TypedDict):
    """State retained by the checkpointed workflow supergraph."""

    discovery_state: dict[str, object]
    solve_states: list[SolveTaskSubstate]
    retrospective_states: Annotated[list[RetrospectiveSubstate], replace_retrospective_states]
    verification_states: list[dict[str, object]]
    final_result_states: list[dict[str, object]]