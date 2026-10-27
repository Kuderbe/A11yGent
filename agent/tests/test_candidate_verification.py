"""Offline contracts for the NVDA-only candidate-verification phase."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.task_verification import verify_candidate


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
                    "content": "I will inspect the suspected condition with NVDA.",
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
            "content": "NVDA announced no confirmation after submission.",
            "reference_id": tool_call["id"],
        }


def test_verify_candidate_confirms_a_complete_barrier_from_nvda_evidence():
    llm = _ScriptedLlm([[_nvda_call()], [_completion_call("confirmed", **_barrier())]])

    outcome = _verify(llm)

    assert outcome == {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.CONFIRMED,
        "evidence": "Speech: no confirmation after submission.",
        "confirmed_barrier": _barrier(),
    }
    assert llm.executed_calls == ["read_speech", "complete_verification"]


def test_verify_candidate_discards_only_with_disconfirming_evidence():
    llm = _ScriptedLlm([[_completion_call("discarded", evidence="NVDA announces the confirmation.")]])

    outcome = _verify(llm)

    assert outcome == {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.DISCARDED,
        "evidence": "NVDA announces the confirmation.",
    }


def test_verify_candidate_marks_budget_exhaustion_as_unverified():
    llm = _ScriptedLlm([[_nvda_call()]])

    outcome = _verify(llm, nvda_max_steps=1)

    assert outcome == {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED,
        "evidence": "The NVDA interaction limit of 1 was reached.",
    }


def test_verify_candidate_records_tool_failure_as_unverified_execution_error():
    llm = _FailingLlm()

    outcome = _verify(llm)

    assert outcome == {
        "candidate_reference": 0,
        "status": VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR,
        "evidence": "NVDA MCP stopped responding.",
        "execution_error": {
            "task_number": 1,
            "phase": "verify",
            "candidate_reference": 0,
            "message": "NVDA MCP stopped responding.",
        },
    }


def test_verify_candidate_rejects_discarding_without_evidence():
    llm = _ScriptedLlm([[_completion_call("discarded", evidence="")]])

    try:
        _verify(llm)
    except RuntimeError as error:
        assert "disconfirming evidence" in str(error)
    else:
        raise AssertionError("Verification must not discard a candidate without evidence")


def test_verify_candidate_rejects_an_incomplete_confirmed_barrier():
    llm = _ScriptedLlm([[_completion_call("confirmed", description="Missing expected behavior.")]])

    try:
        _verify(llm)
    except RuntimeError as error:
        assert "complete barrier" in str(error)
    else:
        raise AssertionError("Verification must not confirm an incomplete barrier")


def test_verify_candidate_rejects_model_claimed_unverified_status():
    llm = _ScriptedLlm([[_completion_call("unverified_budget_exhausted")]])

    try:
        _verify(llm)
    except RuntimeError as error:
        assert "Only runtime failures" in str(error)
    else:
        raise AssertionError("Verification must derive unverified outcomes from runtime failures")


def test_verify_candidate_uses_only_its_fresh_local_prompt():
    llm = _ScriptedLlm([[_completion_call("discarded", evidence="NVDA announces the confirmation.")]])

    _verify(llm)

    prompt = llm.histories[0][0]["content"]
    assert "The confirmation may not be announced." in prompt
    assert "Submit the form and inspect NVDA speech." in prompt
    assert "foreign workflow state" not in prompt


class _FailingLlm(_ScriptedLlm):
    def __init__(self):
        super().__init__([[_nvda_call()]])

    async def execute_tool_call(self, tool_call):
        raise RuntimeError("NVDA MCP stopped responding.")


def _verify(llm, nvda_max_steps=3):
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            return await verify_candidate(
                _config(Path(tmp), nvda_max_steps),
                llm,
                _task(),
                0,
                _candidate(),
                [_nvda_call()["tool"]],
            )

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
    return {"number": 1, "url": "https://shop.example/", "description": "Submit the form."}


def _candidate():
    return {
        "description": "The confirmation may not be announced.",
        "verification_brief": "Submit the form and inspect NVDA speech.",
    }


def _nvda_call():
    return {
        "id": "nvda-1",
        "tool": {"name": "read_speech", "description": "", "tool_function": lambda: None},
        "arguments": {},
    }


def _completion_call(status, evidence="NVDA announced no confirmation after submission.", **barrier):
    return {
        "id": "complete-1",
        "tool": {"name": "complete_verification", "description": "", "tool_function": lambda: None},
        "arguments": {"status": status, "evidence": evidence, **barrier},
    }


def _barrier():
    return {
        "description": "The confirmation is not announced.",
        "expected_behavior": "NVDA announces the confirmation.",
        "actual_behavior": "NVDA announces no confirmation.",
        "reproduction_steps": ["Submit the form."],
        "evidence": "Speech: no confirmation after submission.",
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()