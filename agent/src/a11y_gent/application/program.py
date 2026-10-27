"""Contract and shared resources for independently structured agents."""

from dataclasses import dataclass
from typing import Protocol

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.adaptor.nvda_navigator import TaskNavigator
from a11y_gent.model.assessment_report import AssessmentReport
from a11y_gent.model.run_result import RunResult
from a11y_gent.model.task import Task
from a11y_gent.model.tool import Tool
from a11y_gent.model.workflow import WorkflowTask
from a11y_gent.config import RunConfig


@dataclass(frozen=True)
class RunContext:
    task: Task
    model: str
    max_steps: int
    trajectory_path: str
    llm: LlmClient
    navigator: TaskNavigator
    run_id: str
    workflow_tasks: list[WorkflowTask] | None = None
    discovery_incomplete: bool = False
    discovery_max_steps: int = 150
    report_path: str | None = None
    solve_llm: LlmClient | None = None
    retrospective_llm: LlmClient | None = None
    verification_llm: LlmClient | None = None
    devtools_llm: LlmClient | None = None
    nvda_tools: list[Tool] | None = None
    devtools_tools: list[Tool] | None = None
    workflow_config: RunConfig | None = None


class AgentProgram(Protocol):
    """An independently structured agent variant."""

    id: str

    async def run(self, context: RunContext) -> RunResult | AssessmentReport:
        """Execute the agent variant after common task setup."""