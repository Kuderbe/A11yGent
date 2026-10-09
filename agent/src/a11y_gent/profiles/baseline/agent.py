"""Baseline agent program with its own graph and state."""

import json

from a11y_gent import observability
from a11y_gent.application.program import RunContext
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.run_result import RunResult
from a11y_gent.model.verdict import Verdict, VerdictStatus
from a11y_gent.profiles.baseline.graph import build_graph
from a11y_gent.prompts import build_system_prompt, few_shot_exemplars
from a11y_gent.tooling.extract import extract_barriers, extract_verdict
from a11y_gent.trajectory import to_records


class BaselineAgent:
    id = "baseline-v1"

    async def run(self, context: RunContext) -> RunResult:
        graph = build_graph()
        history = []
        written = 0
        with open(context.trajectory_path, "w", encoding="utf-8") as handle:
            async for state in graph.astream(
                {
                    "llm": context.llm,
                    "task": context.task,
                    "model": context.model,
                    "max_steps": context.max_steps,
                    "discovery_context": self._seed_context(context),
                    "pending_tool_calls": [],
                    "step_count": 0,
                },
                stream_mode="values",
            ):
                records = to_records(state["discovery_context"])
                for record in records[written:]:
                    handle.write(json.dumps(record, ensure_ascii=False))
                    handle.write("\n")
                written = len(records)
                handle.flush()
                history = state["discovery_context"]

        observability.info("trajectory.written", path=context.trajectory_path, record_count=len(history))
        verdict = self._resolve_verdict(history, context.max_steps)
        observability.info("run.result", status=str(verdict["status"]), barrier_count=len(verdict["barriers"]))
        return {"task": context.task, "verdict": verdict, "trajectory_path": context.trajectory_path}

    @staticmethod
    def _seed_context(context: RunContext):
        return [
            {"origin": MessageOrigin.SYSTEM, "content": build_system_prompt(context.task), "name": "system"},
            *few_shot_exemplars(),
            {
                "origin": MessageOrigin.USER,
                "content": f"The page is loaded. Begin the task now. Goal: {context.task['goal']}",
                "name": "user",
            },
        ]

    @staticmethod
    def _resolve_verdict(history, max_steps: int) -> Verdict:
        verdict = extract_verdict(history)
        if verdict is not None:
            return verdict
        return {
            "status": VerdictStatus.FAILED,
            "summary": f"The task could not be solved within {max_steps} steps.",
            "barriers": extract_barriers(history),
        }