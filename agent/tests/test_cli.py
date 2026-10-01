"""Tests for the Typer CLI and task construction (a11y_gent.main, .config).

Offline, no NVDA/network: the CLI's async ``_run`` is replaced by a fake that
records the RunConfig it was given and returns a canned result, so we exercise
argument parsing, env resolution and task construction without a real run.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_cli
"""

import os

from a11y_gent import main as main_module
from a11y_gent.config import build_task
from a11y_gent.model.verdict import VerdictStatus
from typer.testing import CliRunner


_runner = CliRunner()

_ENV = {
    "A11Y_GENT_OPENAI_BASE_URL": "http://base",
    "A11Y_GENT_OPENAI_API_KEY": "key",
}

_FAKE_RESULT = {
    "task": {"url": "u", "goal": "g"},
    "verdict": {"status": VerdictStatus.SUCCEEDED, "summary": "ok", "barriers": []},
    "trajectory_path": "trajectory.jsonl",
}


def _invoke(args, env=None):
    """Run the CLI with ``_run`` stubbed; return (result, captured_config)."""
    captured = {}

    async def _fake_run(config):
        captured["config"] = config
        return _FAKE_RESULT

    original = main_module._run
    main_module._run = _fake_run
    try:
        result = _runner.invoke(
            main_module.app, args, env={**_ENV, **(env or {})}
        )
    finally:
        main_module._run = original
    return result, captured.get("config")


def test_build_task_without_hint_has_no_success_hint():
    task = build_task("http://u", "goal", None)
    assert task == {"url": "http://u", "goal": "goal"}
    assert "success_hint" not in task


def test_build_task_with_hint():
    task = build_task("http://u", "goal", "logged in")
    assert task["success_hint"] == "logged in"


def test_cli_builds_config_from_options():
    result, config = _invoke(
        [
            "--url", "http://x",
            "--goal", "do it",
            "--success-hint", "done when Y",
        ]
    )
    assert result.exit_code == 0, result.output
    assert config.task == {
        "url": "http://x",
        "goal": "do it",
        "success_hint": "done when Y",
    }
    assert config.openai_base_url == "http://base"
    assert config.openai_api_key == "key"
    assert config.model == "gpt-5-mini"
    assert config.max_steps == 30


def test_cli_does_not_require_browser_mcp_options():
    result, config = _invoke(["--url", "http://x", "--goal", "g"])
    assert result.exit_code == 0, result.output
    assert config.nvda_mcp_url == "http://192.168.64.4:8765/mcp"


def test_cli_requires_url_and_goal():
    result, _ = _invoke(["--url", "http://x"])
    assert result.exit_code != 0


def test_cli_reads_model_and_nvda_mcp_url_from_env():
    _, config = _invoke(
        ["--url", "http://x", "--goal", "g"],
        env={
            "A11Y_GENT_MODEL": "gpt-4o",
            "A11Y_GENT_MCP_URL": "http://bridge/mcp",
        },
    )
    assert config.model == "gpt-4o"
    assert config.nvda_mcp_url == "http://bridge/mcp"


def test_cli_options_override_defaults():
    _, config = _invoke(
        [
            "--url", "http://x",
            "--goal", "g",
            "--max-steps", "5",
            "--out", "t.jsonl",
        ]
    )
    assert config.max_steps == 5
    assert config.trajectory_path == "t.jsonl"



def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
