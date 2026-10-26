"""Offline contracts for the NVDA-only solve-task phase."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.task_solving import solve_task
from a11y_gent.workflow_runtime import create_workflow_run


class _ScriptedLlm(LlmClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed_calls = []
        self.histories = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if not use_tools:
            return {
                "message": {
                    "origin": MessageOrigin.ASSISTANT,
                    "name": "assistant",
                    "content": "I will take the next NVDA action.",
                }
            }
        calls = self.responses.pop(0)
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": calls,
            },
            "tool_calls": calls,
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "NVDA observed the current state",
            "reference_id": tool_call["id"],
        }


def test_solve_task_records_direct_barriers_and_continues_to_completion():
    llm = _ScriptedLlm([[_barrier_call()], [_nvda_call()], [_completion_call("succeeded", "Order placed.")]])

    result = _solve(llm)

    assert result["status"] is VerdictStatus.SUCCEEDED
    assert result["summary"] == "Order placed."
    assert result["barriers"] == [_barrier()]
    assert llm.executed_calls == ["report_barrier", "read_speech", "complete_solve_task"]
    barrier_call = llm.histories[2][-2]["tool_calls"][0]
    assert barrier_call["tool"] == {"name": "report_barrier", "description": ""}
    assert "tool_function" not in barrier_call["tool"]


def test_solve_task_fails_at_its_nvda_budget_and_keeps_reported_barriers():
    llm = _ScriptedLlm([[_barrier_call()]])

    result = _solve(llm, nvda_max_steps=1)

    assert result == {
        "status": VerdictStatus.FAILED,
        "summary": "The task could not be solved within 1 steps.",
        "barriers": [_barrier()],
    }


def test_solve_task_keeps_checkpointed_attempts_isolated_by_task_number():
    llm = _ScriptedLlm([[_completion_call("succeeded", "First task done.")], [_completion_call("failed", "Second task blocked.")]])

    first, second = _solve_two_tasks(llm)

    assert first["summary"] == "First task done."
    assert second["status"] is VerdictStatus.FAILED
    assert second["summary"] == "Second task blocked."
    assert llm.executed_calls == ["complete_solve_task", "complete_solve_task"]


def test_solve_task_rejects_multiple_tool_calls_in_one_action_turn():
    llm = _ScriptedLlm([[_barrier_call(), _nvda_call()]])

    try:
        _solve(llm)
    except RuntimeError as error:
        assert "exactly one tool call" in str(error)
    else:
        raise AssertionError("Solve task must not execute multiple tool calls in one action turn")


def test_solve_task_rejects_an_action_turn_without_a_tool_call():
    llm = _ScriptedLlm([[]])

    try:
        _solve(llm)
    except RuntimeError as error:
        assert "exactly one tool call" in str(error)
    else:
        raise AssertionError("Solve task must not accept an action turn without a tool call")


def _solve(llm, nvda_max_steps=3):
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            config = _config(Path(tmp), nvda_max_steps)
            workflow_run = await create_workflow_run(config, "solve-test")
            try:
                return await solve_task(config, llm, workflow_run, _task(), [_nvda_call()["tool"]])
            finally:
                await workflow_run.close()

        return asyncio.run(run())


def _solve_two_tasks(llm):
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            config = _config(Path(tmp), 3)
            workflow_run = await create_workflow_run(config, "solve-test")
            try:
                first = await solve_task(config, llm, workflow_run, _task(), [_nvda_call()["tool"]])
                second = await solve_task(
                    config,
                    llm,
                    workflow_run,
                    {"number": 2, "url": "https://shop.example/", "description": "Review the order."},
                    [_nvda_call()["tool"]],
                )
                return first, second
            finally:
                await workflow_run.close()

        return asyncio.run(run())


def _config(tmp, nvda_max_steps):
    return RunConfig(
        application_url="https://shop.example/",
        task=None,
        model="test-model",
        openai_base_url="https://llm.example/",
        openai_api_key="key",
        nvda_mcp_url="http://nvda.example/mcp",
        trajectory_path=str(tmp / "trajectory.jsonl"),
        nvda_max_steps=nvda_max_steps,
    )


def _task():
    return {"number": 1, "url": "https://shop.example/", "description": "Purchase the first product."}


def _barrier_call():
    return {
        "id": "barrier-1",
        "tool": {"name": "report_barrier", "description": "", "tool_function": lambda: None},
        "arguments": _barrier(),
    }


def _nvda_call():
    return {
        "id": "nvda-1",
        "tool": {"name": "read_speech", "description": "", "tool_function": lambda: None},
        "arguments": {},
    }


def _completion_call(status, summary):
    return {
        "id": "complete-1",
        "tool": {"name": "complete_solve_task", "description": "", "tool_function": lambda: None},
        "arguments": {"status": status, "summary": summary},
    }


def _barrier():
    return {
        "description": "The checkout button has no name.",
        "expected_behavior": "NVDA announces the checkout button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to checkout."],
        "evidence": "Speech: button.",
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()