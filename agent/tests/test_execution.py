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


class _SuccessfulProgram:
    id = "test"

    def __init__(self):
        self.context = None

    async def run(self, context):
        self.context = context
        return {
            "task": context.task,
            "verdict": {"status": "succeeded", "summary": "done", "barriers": []},
            "trajectory_path": context.trajectory_path,
        }


class _Navigator:
    def __init__(self, session):
        self.session = session
        self.opened_url = None

    async def open(self, url):
        self.opened_url = url


def _config(path):
    return RunConfig(
        application_url="http://application.test",
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


def test_execution_runs_the_cli_selected_task_as_task_one():
    original_validate = execution._validate_mcp_endpoint
    original_register = execution.register_mcp_tools
    original_client = execution.Client
    original_llm = execution.OpenaiLlmClient
    original_navigator = execution.McpNvdaNavigator
    original_started = execution.write_started_metadata
    original_result = execution.write_result
    original_select = getattr(execution, "select_cli_tasks", None)
    program = _SuccessfulProgram()
    navigators = []

    async def _validate(endpoint_name, url):
        return None

    async def _register(session):
        return []

    def _select(config):
        return [
            {
                "number": 1,
                "url": "http://application.test",
                "description": "Selected task",
            }
        ]

    def _navigator(session):
        navigator = _Navigator(session)
        navigators.append(navigator)
        return navigator

    try:
        execution._validate_mcp_endpoint = _validate
        execution.register_mcp_tools = _register
        execution.Client = lambda url: _AvailableSession()
        execution.OpenaiLlmClient = lambda *args: object()
        execution.McpNvdaNavigator = _navigator
        execution.write_started_metadata = lambda *args: None
        execution.write_result = lambda *args: None
        execution.select_cli_tasks = _select

        result = asyncio.run(execution.execute(_config(Path("trajectory.jsonl")), program))
    finally:
        execution._validate_mcp_endpoint = original_validate
        execution.register_mcp_tools = original_register
        execution.Client = original_client
        execution.OpenaiLlmClient = original_llm
        execution.McpNvdaNavigator = original_navigator
        execution.write_started_metadata = original_started
        execution.write_result = original_result
        if original_select is None:
            del execution.select_cli_tasks
        else:
            execution.select_cli_tasks = original_select

    assert program.context.task == {"url": "http://application.test", "goal": "Selected task"}
    assert navigators[0].opened_url == "http://application.test"
    assert result["task"] == program.context.task


def test_execution_uses_discovered_task_when_no_cli_task_is_supplied():
    original_validate = execution._validate_mcp_endpoint
    original_discover = getattr(execution, "_discover_tasks", None)
    original_register = execution.register_mcp_tools
    original_client = execution.Client
    original_llm = execution.OpenaiLlmClient
    original_navigator = execution.McpNvdaNavigator
    original_started = execution.write_started_metadata
    original_result = execution.write_result
    program = _SuccessfulProgram()

    async def _validate(endpoint_name, url):
        return None

    async def _discover(config):
        return [
            {
                "number": 1,
                "url": "http://application.test",
                "description": "Discovered task",
            }
        ]

    async def _register(session):
        return []

    try:
        execution._validate_mcp_endpoint = _validate
        execution._discover_tasks = _discover
        execution.register_mcp_tools = _register
        execution.Client = lambda url: _AvailableSession()
        execution.OpenaiLlmClient = lambda *args: object()
        execution.McpNvdaNavigator = lambda session: _Navigator(session)
        execution.write_started_metadata = lambda *args: None
        execution.write_result = lambda *args: None

        result = asyncio.run(execution.execute(_config_without_task(Path("trajectory.jsonl")), program))
    finally:
        execution._validate_mcp_endpoint = original_validate
        execution.register_mcp_tools = original_register
        execution.Client = original_client
        execution.OpenaiLlmClient = original_llm
        execution.McpNvdaNavigator = original_navigator
        execution.write_started_metadata = original_started
        execution.write_result = original_result
        if original_discover is None:
            del execution._discover_tasks
        else:
            execution._discover_tasks = original_discover

    assert program.context.task == {"url": "http://application.test", "goal": "Discovered task"}
    assert result["task"] == program.context.task


def _config_without_task(path):
    return RunConfig(
        application_url="http://application.test",
        task=None,
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        devtools_mcp_url="http://devtools.test/mcp",
        trajectory_path=str(path),
    )


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()