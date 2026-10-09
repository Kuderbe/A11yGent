"""Contract and shared resources for independently structured agents."""

from dataclasses import dataclass
from typing import Protocol

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.adaptor.nvda_navigator import TaskNavigator
from a11y_gent.model.run_result import RunResult
from a11y_gent.model.task import Task


@dataclass(frozen=True)
class RunContext:
    task: Task
    model: str
    max_steps: int
    trajectory_path: str
    llm: LlmClient
    navigator: TaskNavigator
    run_id: str


class AgentProgram(Protocol):
    """An independently structured agent variant."""

    id: str

    async def run(self, context: RunContext) -> RunResult:
        """Execute the agent variant after common task setup."""