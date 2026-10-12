"""Run configuration: every parameter one agent run needs, in one place.

:class:`RunConfig` is an immutable bundle the CLI builds once and hands to
the common application layer. Keeping it separate from the CLI means tests can
construct a config directly, without environment variables or argument parsing.
"""

from dataclasses import dataclass

from a11y_gent.model.task import Task
from a11y_gent.observability import LogLevel


@dataclass(frozen=True)
class RunConfig:
    task: Task
    model: str
    openai_base_url: str
    openai_api_key: str
    nvda_mcp_url: str
    max_steps: int
    trajectory_path: str
    log_level: LogLevel = LogLevel.MINIMAL
    log_file_template: str | None = None


def build_task(url: str, goal: str, success_hint: str | None) -> Task:
    """Build the :class:`Task` from the user-facing inputs."""
    task: Task = {"url": url, "goal": goal}
    if success_hint is not None:
        task["success_hint"] = success_hint
    return task

