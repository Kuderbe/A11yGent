"""The outcome of a single agent run.

Bundles the task that was attempted, the verdict reached, and the path of the
written trajectory. Returned by :class:`a11y_gent.runner.AgentRunner` so callers
get one structured result instead of reading it back off stdout. A run always
has a verdict: if the agent never reports one within the step cap, the runner
records a FAILED verdict for a task it could not solve in that many steps.
"""

from typing import TypedDict

from a11y_gent.model.task import Task
from a11y_gent.model.verdict import Verdict


class RunResult(TypedDict):
    task: Task
    verdict: Verdict
    trajectory_path: str
