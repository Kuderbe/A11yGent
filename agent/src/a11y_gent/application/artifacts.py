"""Persist non-secret metadata shared by all agent programs."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from a11y_gent.application.program import AgentProgram
from a11y_gent.config import RunConfig
from a11y_gent.model.run_result import RunResult


def metadata_path(trajectory_path: str) -> Path:
    path = Path(trajectory_path)
    return path.with_name(f"{path.stem}.metadata.json")


def result_path(trajectory_path: str) -> Path:
    path = Path(trajectory_path)
    return path.with_name(f"{path.stem}.result.json")


def write_started_metadata(config: RunConfig, program: AgentProgram, run_id: str) -> Path:
    path = metadata_path(config.trajectory_path)
    _write_json(
        path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "started_at": _timestamp(),
            "program_id": program.id,
            "program_module": type(program).__module__,
            "task": config.task,
            "model": {"name": config.model, "base_url": config.openai_base_url},
            "max_steps": config.max_steps,
            "agent_git_revision": _git_revision(),
        },
    )
    return path


def write_result(result: RunResult, program: AgentProgram, run_id: str) -> Path:
    path = result_path(result["trajectory_path"])
    _write_json(
        path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "finished_at": _timestamp(),
            "program_id": program.id,
            "task": result["task"],
            "verdict": result["verdict"],
            "trajectory_path": result["trajectory_path"],
        },
    )
    return path


def _write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None