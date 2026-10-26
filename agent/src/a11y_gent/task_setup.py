"""Task-window setup for screen-reader-constrained task attempts."""

from a11y_gent.adaptor.nvda_navigator import TaskNavigator
from a11y_gent.model.workflow import ExecutionError, WorkflowTask


async def setup_solve_task_window(
    navigator: TaskNavigator, task: WorkflowTask
) -> ExecutionError | None:
    """Open one solve-task attempt in a new window, or describe its setup failure."""
    try:
        await navigator.open(task["url"])
    except Exception as exc:
        return {
            "task_number": task["number"],
            "phase": "solve_task",
            "message": f"Could not open a new task window: {exc}",
        }
    return None
