"""Offline durability tests for the checkpointed workflow runtime."""

import asyncio
import tempfile
import json
from pathlib import Path

from a11y_gent.config import RunConfig
from a11y_gent.model.workflow import WorkflowPhase
from a11y_gent.workflow_runtime import (
    create_workflow_run,
    resume_workflow_run,
    resume_workflow_run_from_metadata,
)


def test_workflow_run_persists_phase_context_for_resume():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_persist_phase_context_for_resume(Path(tmp)))


def test_workflow_run_keeps_phase_contexts_isolated_and_records_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_keep_phase_contexts_isolated(Path(tmp)))


def test_workflow_run_writes_resume_metadata_with_stable_identity():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_resume_from_metadata(Path(tmp)))


def test_workflow_run_uses_the_configured_resume_checkpoint_path():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_use_configured_resume_checkpoint_path(Path(tmp)))


def test_workflow_run_keeps_task_contexts_and_writes_chronological_provenance():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_keep_task_contexts_and_provenance(Path(tmp)))


async def _persist_phase_context_for_resume(tmp: Path):
    config = _config(tmp / "trajectory.jsonl")
    run = await create_workflow_run(config, "run-123")
    try:
        await run.record_phase_context(
            WorkflowPhase.DISCOVERY,
            ["Inspect account registration.", "Add a product to the cart."],
        )
        resumed = await resume_workflow_run(run.checkpoint_path, run.checkpoint_id)
        try:
            assert run.checkpoint_id == "run-123"
            assert resumed.checkpoint_id == "run-123"
            assert await resumed.phase_context(WorkflowPhase.DISCOVERY) == [
                "Inspect account registration.",
                "Add a product to the cart.",
            ]
        finally:
            await resumed.close()
    finally:
        await run.close()


async def _keep_phase_contexts_isolated(tmp: Path):
    run = await create_workflow_run(_config(tmp / "trajectory.jsonl"), "run-456")
    try:
        await run.record_phase_context(WorkflowPhase.DISCOVERY, ["Create an account."])
        await run.record_phase_context(
            WorkflowPhase.SOLVE_TASK,
            ["NVDA announced: Create account button."],
            task_number=1,
        )
        await run.record_phase_context(
            WorkflowPhase.VERIFY,
            ["NVDA announced the confirmation message."],
            task_number=1,
            candidate_reference=3,
        )
        assert await run.phase_context(WorkflowPhase.DISCOVERY) == ["Create an account."]
        assert await run.phase_context(WorkflowPhase.SOLVE_TASK, task_number=1) == [
            "NVDA announced: Create account button."
        ]
        assert await run.phase_context(WorkflowPhase.VERIFY, task_number=1, candidate_reference=3) == [
            "NVDA announced the confirmation message."
        ]
        assert run.provenance == [
            {"run_id": "run-456", "phase": "discovery", "task_number": None, "candidate_reference": None},
            {"run_id": "run-456", "phase": "solve_task", "task_number": 1, "candidate_reference": None},
            {"run_id": "run-456", "phase": "verify", "task_number": 1, "candidate_reference": 3},
        ]
    finally:
        await run.close()


async def _resume_from_metadata(tmp: Path):
    run = await create_workflow_run(_config(tmp / "trajectory.jsonl"), "run-789")
    try:
        await run.record_phase_context(WorkflowPhase.DISCOVERY, ["Browse products."])
        resumed = await resume_workflow_run_from_metadata(run.metadata_path)
        try:
            assert run.metadata_path.exists()
            assert resumed.checkpoint_id == "run-789"
            assert resumed.checkpoint_path == run.checkpoint_path
            assert await resumed.phase_context(WorkflowPhase.DISCOVERY) == ["Browse products."]
        finally:
            await resumed.close()
    finally:
        await run.close()


async def _use_configured_resume_checkpoint_path(tmp: Path):
    checkpoint_path = tmp / "resume.sqlite"
    config = _config(tmp / "trajectory.jsonl", resume_path=str(checkpoint_path))
    run = await create_workflow_run(config, "run-resume")
    try:
        assert run.checkpoint_path == checkpoint_path.resolve()
        assert run.metadata_path == (tmp / "resume.metadata.json").resolve()
    finally:
        await run.close()


async def _keep_task_contexts_and_provenance(tmp: Path):
    run = await create_workflow_run(_config(tmp / "trajectory.jsonl"), "run-101")
    try:
        await run.record_phase_context(WorkflowPhase.SOLVE_TASK, ["Task one."], task_number=1)
        await run.record_phase_context(WorkflowPhase.SOLVE_TASK, ["Task two."], task_number=2)
        assert await run.phase_context(WorkflowPhase.SOLVE_TASK, task_number=1) == ["Task one."]
        assert await run.phase_context(WorkflowPhase.SOLVE_TASK, task_number=2) == ["Task two."]
        assert [json.loads(line) for line in run.provenance_path.read_text(encoding="utf-8").splitlines()] == [
            {"run_id": "run-101", "phase": "solve_task", "task_number": 1, "candidate_reference": None},
            {"run_id": "run-101", "phase": "solve_task", "task_number": 2, "candidate_reference": None},
        ]
    finally:
        await run.close()


def _config(trajectory_path: Path, resume_path: str | None = None) -> RunConfig:
    return RunConfig(
        application_url="http://application.test",
        task=None,
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        trajectory_path=str(trajectory_path),
        resume_path=resume_path,
    )


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()