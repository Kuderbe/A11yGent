"""Tests for the baseline agent program.

Offline, no NVDA/network: a scripted fake LlmClient plays back a sequence of
think/act responses, so the whole reason -> act -> observe loop runs in-process.
Verifies that the runner drives the loop to a reported verdict, writes the
trajectory, and normalises a run that hits the step cap without a verdict into a
FAILED verdict.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_runner
"""

import asyncio
import json
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.application.program import RunContext
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.profiles.baseline.agent import BaselineAgent
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.verdict import make_verdict_tool


_VERDICT_TOOL = make_verdict_tool()
_BARRIER_TOOL = make_barrier_tool()


def _tool_call(tool, call_id, arguments):
    return {"id": call_id, "tool": tool, "arguments": arguments}


class _ScriptedLlm(LlmClient):
    """Replays a fixed list of responses; think turns get plain text.

    ``infer`` returns the next scripted response on an action turn and a plain
    thought on a reasoning turn, matching the think -> act rhythm of the graph.
    ``execute_tool_call`` runs the no-op tool and returns its result message.
    """

    def __init__(self, action_responses):
        self._action_responses = list(action_responses)

    async def infer(self, history, model, use_tools=True):
        thought = {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": "thinking",
        }
        if not use_tools:
            return {"message": thought}

        response = self._action_responses.pop(0)
        message = {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": "",
            "tool_calls": response,
        }
        return {"message": message, "tool_calls": response}

    async def execute_tool_call(self, tool_call):
        result = tool_call["tool"]["tool_function"](**tool_call["arguments"])
        return {
            "origin": MessageOrigin.TOOL,
            "content": str(result),
            "name": tool_call["tool"]["name"],
            "reference_id": tool_call["id"],
        }


class _FailingToolLlm(_ScriptedLlm):
    async def execute_tool_call(self, tool_call):
        raise RuntimeError("simulated crash inside execute_tools_node")


_TASK = {"url": "http://example.test/barrier.html", "goal": "Do the thing."}
_BARRIER_ARGUMENTS = {
    "description": "d",
    "expected_behavior": "expected",
    "actual_behavior": "actual",
    "reproduction_steps": ["step"],
    "evidence": "e",
}


class _FakeNavigator:
    """Records the URL it was asked to open; does nothing else."""

    def __init__(self):
        self.opened = None

    async def open(self, url):
        self.opened = url


def _run(llm, max_steps=30):
    navigator = _FakeNavigator()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "trajectory.jsonl")
        result = asyncio.run(
            BaselineAgent().run(
                RunContext(_TASK, "m", max_steps, path, llm, navigator, "test-run")
            )
        )
        records = [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
        ]
    return result, records, navigator


def test_runner_returns_reported_verdict_and_barriers():
    llm = _ScriptedLlm(
        [
            [_tool_call(_BARRIER_TOOL, "b1", _BARRIER_ARGUMENTS)],
            [_tool_call(_VERDICT_TOOL, "v1", {"status": "failed", "summary": "blocked"})],
        ]
    )

    result, _, _ = _run(llm)

    assert result["task"] == _TASK
    assert result["verdict"]["status"] == VerdictStatus.FAILED
    assert result["verdict"]["summary"] == "blocked"
    assert len(result["verdict"]["barriers"]) == 1
    assert result["verdict"]["barriers"][0]["description"] == "d"


def test_runner_writes_trajectory():
    llm = _ScriptedLlm(
        [[_tool_call(_VERDICT_TOOL, "v1", {"status": "succeeded", "summary": "ok"})]]
    )

    _, records, _ = _run(llm)

    assert records[0]["phase"] == "context"
    assert records[0]["message_role"] == "system"
    assert any(r["phase"] == "act" for r in records)


def test_runner_preserves_trajectory_when_a_tool_fails():
    llm = _FailingToolLlm(
        [[_tool_call(_BARRIER_TOOL, "b1", _BARRIER_ARGUMENTS)]]
    )
    navigator = _FakeNavigator()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trajectory.jsonl"
        try:
            asyncio.run(
                BaselineAgent().run(
                    RunContext(_TASK, "m", 30, str(path), llm, navigator, "test-run")
                )
            )
        except RuntimeError as error:
            assert str(error) == "simulated crash inside execute_tools_node"
        else:
            raise AssertionError("Expected the simulated tool failure")

        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert records
    assert records[-1]["phase"] == "act"
    assert records[-1]["tool_calls"][0]["id"] == "b1"


def test_runner_normalises_step_cap_to_failed_verdict():
    # Never reports a verdict: every action turn only reports a barrier, so the
    # loop runs until the step cap and the runner must synthesise a verdict.
    llm = _ScriptedLlm(
        [[_tool_call(_BARRIER_TOOL, f"b{i}", _BARRIER_ARGUMENTS)]
         for i in range(50)]
    )

    result, _, _ = _run(llm, max_steps=4)

    assert result["verdict"]["status"] == VerdictStatus.FAILED
    assert "4 steps" in result["verdict"]["summary"]



def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
