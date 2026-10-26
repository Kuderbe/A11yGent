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


def test_supergraph_persists_nested_retrospective_state_for_resume():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_persist_nested_state_for_resume(Path(tmp)))


async def _persist_nested_state_for_resume(tmp: Path):
    llm = _ScriptedLlm()
    dependencies = WorkflowDependencies(retrospective_llm=llm, retrospective_model="test-model")
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
    assert "candidates" not in completed
    assert "confirmed_barriers" not in completed
    assert "task_results" not in completed


def test_supergraph_projects_only_retrospective_local_state_to_its_llm():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_keep_llm_context_local(Path(tmp)))


def test_supergraph_exposes_native_retrospective_subgraph_state():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_expose_native_retrospective_subgraph_state(Path(tmp)))


async def _expose_native_retrospective_subgraph_state(tmp: Path):
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-789",
        WorkflowDependencies(retrospective_llm=_ScriptedLlm(), retrospective_model="test-model"),
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
    state["verification_states"] = [{"foreign": "Must not enter the prompt."}]
    state["final_result_states"] = [{"foreign": "Must not enter the prompt."}]
    run = await create_workflow_run(
        _config(tmp / "trajectory.jsonl"),
        "run-456",
        WorkflowDependencies(retrospective_llm=llm, retrospective_model="test-model"),
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
        "verification_states": [{}],
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