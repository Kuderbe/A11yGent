"""Offline contracts for the checkpointed workflow supergraph."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.task_retrospective import initial_retrospective_state
from a11y_gent.workflow_runtime import (
    WorkflowDependencies,
    create_workflow_run,
    resume_workflow_run,
)


class _ScriptedLlm(LlmClient):
    def __init__(self):
        self.histories = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "retrospective-1",
                        "tool": {
                            "name": "complete_retrospective",
                            "description": "",
                            "tool_function": lambda: None,
                        },
                        "arguments": {
                            "descriptions": ["The confirmation might not be announced."],
                            "verification_briefs": ["Submit and inspect NVDA speech."],
                        },
                    }
                ],
            },
            "tool_calls": [
                {
                    "id": "retrospective-1",
                    "tool": {
                        "name": "complete_retrospective",
                        "description": "",
                        "tool_function": lambda: None,
                    },
                    "arguments": {
                        "descriptions": ["The confirmation might not be announced."],
                        "verification_briefs": ["Submit and inspect NVDA speech."],
                    },
                }
            ],
        }

    async def execute_tool_call(self, tool_call):
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "retrospective completed",
            "reference_id": tool_call["id"],
        }


class _VerificationLlm(LlmClient):
    def __init__(self):
        self.executed_calls = []
        self.histories = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if not use_tools:
            return {
                "message": {
                    "origin": MessageOrigin.ASSISTANT,
                    "name": "assistant",
                    "content": "I will inspect this candidate with NVDA.",
                }
            }
        candidate = "first" if "first candidate" in history[0]["content"] else "second"
        call = {
            "id": f"complete-{candidate}",
            "tool": {
                "name": "complete_verification",
                "description": "",
                "tool_function": lambda: None,
            },
            "arguments": {
                "status": "discarded",
                "evidence": f"NVDA disproved {candidate} candidate.",
            },
        }
        return {
            "message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]},
            "tool_calls": [call],
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "verification completed",
            "reference_id": tool_call["id"],
        }


class _FailIfCalledLlm(LlmClient):
    async def infer(self, history, model, use_tools=True):
        raise AssertionError("No LLM call is allowed for an empty candidate list")

    async def execute_tool_call(self, tool_call):
        raise AssertionError("No tool call is allowed for an empty candidate list")


def test_supergraph_persists_nested_retrospective_state_for_resume():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_persist_nested_state_for_resume(Path(tmp)))


async def _persist_nested_state_for_resume(tmp: Path):
    llm = _ScriptedLlm()
    dependencies = _dependencies(retrospective_llm=llm)
    run = await create_workflow_run(_config(tmp / "trajectory.jsonl"), "run-123", dependencies)
    try:
        completed = await run.invoke(_workflow_state())
        resumed = await resume_workflow_run(run.checkpoint_path, run.checkpoint_id, dependencies)
        try:
            persisted = await resumed.state()
        finally:
            await resumed.close()
    finally:
        await run.close()

    assert completed["retrospective_states"][0]["candidates"] == [
        {
            "description": "The confirmation might not be announced.",
            "verification_brief": "Submit and inspect NVDA speech.",
        }
    ]
    assert persisted == completed
    assert persisted["verification_states"][0]["candidate_reference"] == 0
    assert "candidates" not in completed
    assert "confirmed_barriers" not in completed
    assert "task_results" not in completed


def test_supergraph_projects_only_retrospective_local_state_to_its_llm():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_keep_llm_context_local(Path(tmp)))


def test_supergraph_exposes_native_retrospective_subgraph_state():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_expose_native_retrospective_subgraph_state(Path(tmp)))


def test_supergraph_verifies_retrospective_candidates_in_local_order():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_verify_candidates_in_local_order(Path(tmp)))


def test_supergraph_skips_verification_for_completed_empty_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_skip_empty_candidates(Path(tmp)))


async def _verify_candidates_in_local_order(tmp: Path):
    verification_llm = _VerificationLlm()
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-verify-order",
        _dependencies(verification_llm),
    )
    state = _workflow_state()
    state["retrospective_states"] = [_completed_retrospective_state([_candidate("first"), _candidate("second")])]
    try:
        completed = await run.invoke(state)
    finally:
        await run.close()

    assert [verification["candidate_reference"] for verification in completed["verification_states"]] == [0, 1], completed
    assert [verification["candidate"]["description"] for verification in completed["verification_states"]] == [
        "first candidate",
        "second candidate",
    ]
    assert [verification["outcome"]["evidence"] for verification in completed["verification_states"]] == [
        "NVDA disproved first candidate.",
        "NVDA disproved second candidate.",
    ]
    assert verification_llm.executed_calls == ["complete_verification", "complete_verification"]
    action_histories = verification_llm.histories[1::2]
    assert [len(history) for history in action_histories] == [2, 2]


async def _skip_empty_candidates(tmp: Path):
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-empty-candidates",
        _dependencies(verification_llm=_FailIfCalledLlm(), retrospective_llm=_FailIfCalledLlm()),
    )
    state = _workflow_state()
    state["retrospective_states"] = [_completed_empty_retrospective_state()]
    try:
        completed = await run.invoke(state)
    finally:
        await run.close()

    assert completed["verification_states"] == []


async def _expose_native_retrospective_subgraph_state(tmp: Path):
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-789",
        _dependencies(),
    )
    try:
        completed = await run.invoke(_workflow_state())
    finally:
        await run.close()

    assert completed["retrospective_states"][0]["candidates"] == [
        {
            "description": "The confirmation might not be announced.",
            "verification_brief": "Submit and inspect NVDA speech.",
        }
    ]


async def _keep_llm_context_local(tmp: Path):
    llm = _ScriptedLlm()
    state = _workflow_state()
    solve_task_history = [
        *_solve_history(),
        {
            "origin": MessageOrigin.TOOL,
            "name": "devtools_only",
            "content": "Must not be passed to retrospective.",
            "reference_id": "devtools-1",
        },
    ]
    state["retrospective_states"] = [initial_retrospective_state(_task(), solve_task_history)]
    state["verification_states"] = []
    state["final_result_states"] = [{"foreign": "Must not enter the prompt."}]
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-456",
        _dependencies(retrospective_llm=llm),
    )
    try:
        completed = await run.invoke(state)
    finally:
        await run.close()

    assert completed["retrospective_states"][0]["candidates"]
    prompt = completed["retrospective_states"][0]["history"][0]["content"]
    assert "Must not be passed" in prompt
    assert "foreign" not in prompt
    assert "verification_states" not in prompt


def _task():
    return {"number": 1, "url": "https://shop.example/", "description": "Purchase a product."}


def _candidate(name):
    return {"description": f"{name} candidate", "verification_brief": f"Check {name} with NVDA."}


def _completed_empty_retrospective_state():
    return _completed_retrospective_state([])


def _completed_retrospective_state(candidates):
    state = initial_retrospective_state(_task(), _solve_history())
    return {
        **state,
        "history": [
            *state["history"],
            {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "retrospective-empty",
                        "tool": {"name": "complete_retrospective", "description": ""},
                        "arguments": {
                            "descriptions": [candidate["description"] for candidate in candidates],
                            "verification_briefs": [candidate["verification_brief"] for candidate in candidates],
                        },
                    }
                ],
            },
        ],
        "candidates": candidates,
    }


def _nvda_tool():
    return {"name": "read_speech", "description": "", "tool_function": lambda: None}


def _dependencies(verification_llm=None, retrospective_llm=None):
    return WorkflowDependencies(
        retrospective_llm=retrospective_llm or _ScriptedLlm(),
        retrospective_model="test-model",
        verification_llm=verification_llm or _VerificationLlm(),
        verification_model="test-model",
        nvda_tools=[_nvda_tool()],
        nvda_max_steps=3,
    )


def _solve_history():
    return [
        {
            "origin": MessageOrigin.TOOL,
            "name": "read_speech",
            "content": "No confirmation followed submission.",
            "reference_id": "speech-1",
        }
    ]


def _workflow_state():
    return {
        "discovery_state": {},
        "solve_states": [{"task": _task(), "history": _solve_history()}],
        "retrospective_states": [initial_retrospective_state(_task(), _solve_history())],
        "verification_states": [],
        "final_result_states": [{}],
    }


def _config(trajectory_path: Path) -> RunConfig:
    return RunConfig(
        application_url="https://shop.example/",
        task=None,
        model="test-model",
        openai_base_url="https://llm.example/",
        openai_api_key="key",
        nvda_mcp_url="http://nvda.example/mcp",
        trajectory_path=str(trajectory_path),
    )


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()