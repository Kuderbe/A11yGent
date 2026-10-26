"""Offline tests for shared run metadata and result artifacts.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_artifacts
"""

import json
import tempfile
from pathlib import Path

from a11y_gent.application.artifacts import write_result, write_started_metadata
from a11y_gent.config import RunConfig
from a11y_gent.model.verdict import VerdictStatus
from a11y_gent.observability import LogLevel


class _Program:
    id = "test-program-v1"


def test_metadata_records_program_without_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        trajectory = str(Path(tmp) / "run.trajectory.jsonl")
        config = RunConfig(
            task={"url": "http://example.test", "goal": "Test it"},
            model="model",
            openai_base_url="http://endpoint",
            openai_api_key="secret",
            nvda_mcp_url="http://mcp",
            trajectory_path=trajectory,
            discovery_max_steps=8,
            nvda_max_steps=7,
            log_level=LogLevel.INFO,
        )
        path = write_started_metadata(config, _Program(), "run-1")
        content = path.read_text(encoding="utf-8")
        record = json.loads(content)

    assert record["program_id"] == "test-program-v1"
    assert record["task"] == config.task
    assert record["model"] == {"name": "model", "base_url": "http://endpoint"}
    assert record["discovery_max_steps"] == 8
    assert record["nvda_max_steps"] == 7
    assert "secret" not in content


def test_result_records_verdict_and_program():
    with tempfile.TemporaryDirectory() as tmp:
        trajectory = str(Path(tmp) / "run.trajectory.jsonl")
        result = {
            "task": {"url": "http://example.test", "goal": "Test it"},
            "verdict": {"status": VerdictStatus.SUCCEEDED, "summary": "done", "barriers": []},
            "trajectory_path": trajectory,
        }
        path = write_result(result, _Program(), "run-1")
        record = json.loads(path.read_text(encoding="utf-8"))

    assert record["program_id"] == "test-program-v1"
    assert record["verdict"]["status"] == "succeeded"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()