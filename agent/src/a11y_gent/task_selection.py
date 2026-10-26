"""Select supplied tasks for the phased assessment workflow."""

from a11y_gent.config import RunConfig
from a11y_gent.model.workflow import WorkflowTask


def select_cli_tasks(config: RunConfig) -> list[WorkflowTask]:
    """Return the supplied CLI task as the first enumerated workflow task."""
    if config.task is None:
        return []
    return [
        {
            "number": 1,
            "url": config.application_url,
            "description": config.task["goal"],
        }
    ]