"""Orchestrate a single agent run.

:class:`AgentRunner` navigates the browser to the task URL (setup, via a
:class:`~a11y_gent.adaptor.browser_navigator.BrowserNavigator`), seeds the
conversation (system prompt, few-shot exemplars, the task), drives the reason ->
act -> observe loop to completion, writes the trajectory, and returns a
:class:`RunResult`. A run always yields a verdict: if the agent never reports
one within the step cap, the runner records a FAILED verdict for a task it could
not solve in that many steps.
"""

from a11y_gent.adaptor.browser_navigator import BrowserNavigator
from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.run_result import RunResult
from a11y_gent.model.task import Task
from a11y_gent.model.verdict import Verdict, VerdictStatus
from a11y_gent.prompts import build_system_prompt, few_shot_exemplars
from a11y_gent.runtime import build_agent_graph
from a11y_gent.tooling.extract import extract_barriers, extract_verdict
from a11y_gent.trajectory import write_jsonl


class AgentRunner:
    """Run one task with a configured LLM client and return the result."""

    def __init__(
        self,
        llm: LlmClient,
        navigator: BrowserNavigator,
        task: Task,
        model: str,
        max_steps: int,
        trajectory_path: str,
    ):
        self._llm = llm
        self._navigator = navigator
        self._task = task
        self._model = model
        self._max_steps = max_steps
        self._trajectory_path = trajectory_path

    async def run(self) -> RunResult:
        # Setup: load the page the agent will then read through NVDA only.
        await self._navigator.open(self._task["url"])

        graph = build_agent_graph()

        res = await graph.ainvoke(
            {
                "llm": self._llm,
                "task": self._task,
                "model": self._model,
                "max_steps": self._max_steps,
                "discovery_context": self._seed_context(),
                "pending_tool_calls": [],
                "step_count": 0,
            }
        )

        history = res["discovery_context"]
        write_jsonl(history, self._trajectory_path)

        return {
            "task": self._task,
            "verdict": self._resolve_verdict(history),
            "trajectory_path": self._trajectory_path,
        }

    def _seed_context(self):
        return [
            {
                "origin": MessageOrigin.SYSTEM,
                "content": build_system_prompt(self._task),
                "name": "system",
            },
            *few_shot_exemplars(),
            {
                "origin": MessageOrigin.USER,
                "content": (
                    f"The page is loaded. Begin the task now. "
                    f"Goal: {self._task['goal']}"
                ),
                "name": "user",
            },
        ]

    def _resolve_verdict(self, history) -> Verdict:
        verdict = extract_verdict(history)
        if verdict is not None:
            return verdict

        # The loop hit the step cap without a reported verdict: the agent could
        # not solve the task in the allotted number of steps.
        return {
            "status": VerdictStatus.FAILED,
            "summary": (
                f"The task could not be solved within {self._max_steps} steps."
            ),
            "barriers": extract_barriers(history),
        }

