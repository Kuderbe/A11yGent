"""Offline startup-validation tests for the shared execution lifecycle."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.application import execution
from a11y_gent.config import RunConfig


class _UnavailableSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def list_tools(self):
        raise ConnectionError("endpoint refused connection")


class _AvailableSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def list_tools(self):
        return []


class _ClientFactory:
    def __init__(self, unavailable_url):
        self.unavailable_url = unavailable_url

    def __call__(self, url):
        if url == self.unavailable_url:
            return _UnavailableSession()
        return _AvailableSession()


class _Program:
    id = "test"

    def __init__(self):
        self.ran = False

    async def run(self, context):
        self.ran = True
        raise AssertionError("The program must not run after startup validation fails")


def _config(path):
    return RunConfig(
        task={"url": "http://application.test", "goal": "Complete the task"},
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        devtools_mcp_url="http://devtools.test/mcp",
        trajectory_path=str(path),
    )


def _assert_unavailable_endpoint_stops_execution(unavailable_url, expected_endpoint):
    original_client = execution.Client
    program = _Program()
    try:
        execution.Client = _ClientFactory(unavailable_url)
        with tempfile.TemporaryDirectory() as tmp:
            trajectory_path = Path(tmp) / "trajectory.jsonl"
            try:
                asyncio.run(execution.execute(_config(trajectory_path), program))
            except RuntimeError as error:
                assert expected_endpoint in str(error)
                assert unavailable_url in str(error)
            else:
                raise AssertionError("Expected startup validation to fail")

            assert not trajectory_path.exists()
            assert not trajectory_path.with_name("trajectory.metadata.json").exists()
            assert not trajectory_path.with_name("trajectory.result.json").exists()
    finally:
        execution.Client = original_client

    assert program.ran is False


def test_execution_stops_before_task_work_when_devtools_mcp_is_unavailable():
    _assert_unavailable_endpoint_stops_execution("http://devtools.test/mcp", "Chrome DevTools")


def test_execution_stops_before_task_work_when_nvda_mcp_is_unavailable():
    _assert_unavailable_endpoint_stops_execution("http://nvda.test/mcp", "NVDA")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()