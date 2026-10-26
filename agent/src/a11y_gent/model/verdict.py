"""The task-level accessibility verdict the agent produces for a task.

This is A11yGent's core output: an explicit, structured decision the agent
reports through the ``report_verdict`` tool.
"""

from enum import Enum
from typing import TypedDict


class VerdictStatus(Enum):
    """Outcome of attempting a task under a screen-reader profile."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUCCEEDED_WITH_AVOIDABLE_DIFFICULTY = "succeeded_with_avoidable_difficulty"

    def __str__(self) -> str:
        return self.value


class Barrier(TypedDict):
    """A single accessibility barrier encountered while attempting the task.

    ``description``        - human-readable explanation of what a real user hits.
    ``expected_behavior``  - the screen-reader behaviour a user should receive.
    ``actual_behavior``    - the observed screen-reader behaviour.
    ``reproduction_steps`` - executed steps that reproduce the condition.
    ``evidence``           - grounding for the barrier: NVDA speech-log entry
                             ids, a focus snapshot, quoted spoken text, etc.
    """

    description: str
    expected_behavior: str
    actual_behavior: str
    reproduction_steps: list[str]
    evidence: str


class Verdict(TypedDict):
    """The structured result of a single task attempt."""

    status: VerdictStatus
    summary: str
    barriers: list[Barrier]
