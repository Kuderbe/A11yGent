"""Offline contracts for the checkpointed phased baseline program."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.application.program import RunContext
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.profiles.baseline_v2.agent import BaselineV2


def test_baseline_v2_runs_one_task_and_writes_the_complete_report():
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "assessment.md"
        config = _config(Path(tmp), report_path)
        context = _context(config, report_path)
        report = asyncio.run(BaselineV2().run(context))

        assert "# Accessibility assessment report" in report.to_markdown()
        assert report_path.read_text(encoding="utf-8") == report.to_markdown()
        assert context.navigator.opened == [config.application_url]
        assert Path(config.trajectory_path).with_name("trajectory.workflow.sqlite").exists()


def test_baseline_v2_creates_then_resumes_an_explicit_checkpoint():
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint_path = Path(tmp) / "workflow.sqlite"
        config = _config(Path(tmp), Path(tmp) / "assessment.md")
        config = RunConfig(**{**config.__dict__, "resume_path": str(checkpoint_path)})
        asyncio.run(BaselineV2().run(_context(config, Path(tmp) / "assessment.md")))
        resumed = asyncio.run(BaselineV2().run(_context(config, Path(tmp) / "resumed.md")))

        assert checkpoint_path.exists()
        assert "# Accessibility assessment report" in resumed.to_markdown()


def _config(tmp, report_path):
    return RunConfig(
        application_url="https://shop.example/",
        task={"url": "https://shop.example/", "goal": "Complete checkout"},
        model="test-model",
        openai_base_url="https://llm.example/",
        openai_api_key="key",
        nvda_mcp_url="http://nvda.example/mcp",
        devtools_mcp_url="http://devtools.example/mcp",
        trajectory_path=str(tmp / "trajectory.jsonl"),
        report_path=str(report_path),
        discovery_max_steps=3,
        nvda_max_steps=3,
    )


def _context(config, report_path):
    task = {"number": 1, "url": config.application_url, "description": "Complete checkout"}
    return RunContext(
        {"url": config.application_url, "goal": task["description"]},
        config.model,
        config.nvda_max_steps,
        config.trajectory_path,
        _PhasedLlm(),
        _Navigator(),
        "run-1",
        workflow_tasks=[task],
        discovery_max_steps=config.discovery_max_steps,
        report_path=str(report_path),
        solve_llm=_PhasedLlm(),
        retrospective_llm=_PhasedLlm(),
        verification_llm=_PhasedLlm(),
        devtools_llm=_PhasedLlm(),
        nvda_tools=[],
        devtools_tools=[],
        workflow_config=config,
    )


class _PhasedLlm(LlmClient):
    async def infer(self, history, model, use_tools=True):
        if not use_tools:
            return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "I will complete this phase."}}
        phase = history[0]["name"]
        if phase == "solve_task":
            call = _call("complete_solve_task", {"status": "succeeded", "summary": "Checkout completed."})
        elif phase == "retrospective":
            call = _call("complete_retrospective", {"descriptions": [], "verification_briefs": []})
        else:
            raise AssertionError(f"Unexpected phase {phase}")
        return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]}, "tool_calls": [call]}

    async def execute_tool_call(self, tool_call):
        return {"origin": MessageOrigin.TOOL, "name": tool_call["tool"]["name"], "content": "completed", "reference_id": tool_call["id"]}


class _Navigator:
    def __init__(self):
        self.opened = []

    async def open(self, url):
        self.opened.append(url)


def _call(name, arguments):
    return {"id": name, "tool": {"name": name, "description": "", "tool_function": lambda: None}, "arguments": arguments}


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()