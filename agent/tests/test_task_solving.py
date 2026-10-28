"""Offline contracts for the NVDA-only solve-task phase."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.task_solving import solve_task


class _ScriptedLlm(LlmClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed_calls = []
        self.reason_turn = True
        self.histories = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if self.reason_turn:
            self.reason_turn = False
            return {
                "message": {
                    "origin": MessageOrigin.ASSISTANT,
                    "name": "assistant",
                    "content": "I will take the next NVDA action.",
                }
            }
        self.reason_turn = True
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
    barrier_call = next(
        call
        for history in llm.histories
        for message in history
        for call in message.get("tool_calls", [])
        if call["tool"]["name"] == "report_barrier"
    )
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


def test_solve_task_keeps_attempts_isolated_by_task_number():
    llm = _ScriptedLlm([[_completion_call("succeeded", "First task done.")], [_completion_call("failed", "Second task blocked.")]])

    first, second = _solve_two_tasks(llm)

    assert first["summary"] == "First task done."
    assert second["status"] is VerdictStatus.FAILED
    assert second["summary"] == "Second task blocked."
    assert llm.executed_calls == ["complete_solve_task", "complete_solve_task"]


def test_solve_task_observes_a_rejected_multiple_call_before_retrying():
    llm = _ScriptedLlm([[_barrier_call(), _nvda_call()], [_completion_call("succeeded", "Order placed.")]])

    result = _solve(llm)

    assert result["status"] is VerdictStatus.SUCCEEDED
    assert llm.executed_calls == ["complete_solve_task"]
    observation = _observation(llm, "received 2")
    assert observation["origin"] is MessageOrigin.TOOL
    assert "received 2" in observation["content"]


def test_solve_task_observes_a_rejected_missing_call_before_retrying():
    llm = _ScriptedLlm([[], [_completion_call("succeeded", "Order placed.")]])

    result = _solve(llm)

    assert result["status"] is VerdictStatus.SUCCEEDED
    assert llm.executed_calls == ["complete_solve_task"]
    observation = _observation(llm, "received 0")
    assert observation["name"] == "action_contract"
    assert "received 0" in observation["content"]


def test_solve_task_counts_a_rejected_action_against_its_budget():
    llm = _ScriptedLlm([[]])

    result = _solve(llm, nvda_max_steps=1)

    assert result["status"] is VerdictStatus.FAILED
    assert llm.executed_calls == []


def test_solve_task_observes_unknown_and_invalid_argument_calls_before_retrying():
    unknown = {"id": "unknown", "tool": {"name": "missing", "description": "", "tool_function": lambda: None}, "arguments": {}}
    invalid = {"id": "invalid", "tool": {"name": "read_speech", "description": "", "tool_function": lambda: None}, "arguments": {"unexpected": True}}
    llm = _ScriptedLlm([[unknown], [invalid], [_completion_call("succeeded", "Order placed.")]])

    result = _solve(llm)

    assert result["status"] is VerdictStatus.SUCCEEDED
    assert llm.executed_calls == ["complete_solve_task"]
    assert "unknown tool 'missing'" in _observation(llm, "unknown tool 'missing'")["content"]
    assert "invalid arguments for 'read_speech'" in _observation(llm, "invalid arguments for 'read_speech'")["content"]


def test_solve_task_uses_reason_call_when_act_has_no_call():
    llm = _ReasonFallbackLlm()

    result = _solve(llm)

    assert result["status"] is VerdictStatus.SUCCEEDED
    assert llm.act_turns == 1
    assert llm.executed_calls == ["complete_solve_task"]


def test_solve_task_prefers_act_call_over_reason_call():
    llm = _ReasonAndActLlm()

    result = _solve(llm)

    assert result["summary"] == "Act completed the task."
    assert llm.executed_calls == ["complete_solve_task"]


def _solve(llm, nvda_max_steps=3):
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            config = _config(Path(tmp), nvda_max_steps)
            return await solve_task(config, llm, _task(), [_nvda_call()["tool"]])

        return asyncio.run(run())


def _observation(llm, text):
    return next(
        message
        for history in llm.histories
        for message in history
        if text in message["content"]
    )


def _solve_two_tasks(llm):
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            config = _config(Path(tmp), 3)
            first = await solve_task(config, llm, _task(), [_nvda_call()["tool"]])
            second = await solve_task(
                config,
                llm,
                {"number": 2, "url": "https://shop.example/", "description": "Review the order."},
                [_nvda_call()["tool"]],
            )
            return first, second

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
        retrospective_max_iterations=20,
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


class _ReasonFallbackLlm(LlmClient):
    def __init__(self):
        self.histories = []
        self.executed_calls = []
        self.act_turns = 0

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if len(self.histories) == 1:
            call = _completion_call("succeeded", "Order placed.")
            return {
                "message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]},
                "tool_calls": [call],
            }
        self.act_turns += 1
        return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": ""}}

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {"origin": MessageOrigin.TOOL, "name": tool_call["tool"]["name"], "content": "done", "reference_id": tool_call["id"]}


class _ReasonAndActLlm(LlmClient):
    def __init__(self):
        self.histories = []
        self.executed_calls = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        summary = "Reason completed the task." if len(self.histories) == 1 else "Act completed the task."
        call = _completion_call("succeeded", summary)
        return {
            "message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]},
            "tool_calls": [call],
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {"origin": MessageOrigin.TOOL, "name": tool_call["tool"]["name"], "content": "done", "reference_id": tool_call["id"]}


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