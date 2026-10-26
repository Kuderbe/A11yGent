"""Shared infrastructure lifecycle around an agent program."""

from a11y_gent import observability
from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.nvda_navigator import McpNvdaNavigator
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.application.artifacts import write_result, write_started_metadata
from a11y_gent.application.program import AgentProgram, RunContext
from a11y_gent.config import RunConfig
from a11y_gent.main_support import additional_headers_for
from a11y_gent.model.task import Task
from a11y_gent.model.workflow import WorkflowPhase, WorkflowTask
from a11y_gent.prompts import make_discovery_completion_tool
from a11y_gent.task_discovery import discover_tasks
from a11y_gent.task_selection import select_cli_tasks
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.phase_tools import tools_for_phase
from a11y_gent.tooling.verdict import make_verdict_tool
from mcp import Client


async def _validate_mcp_endpoint(endpoint_name: str, url: str) -> None:
    """Confirm that an MCP endpoint accepts a session and serves tools."""
    try:
        async with Client(url) as session:
            await session.list_tools()
    except Exception as exc:
        raise RuntimeError(
            f"{endpoint_name} MCP endpoint is unavailable at {url}: {exc}"
        ) from exc


async def execute(config: RunConfig, program: AgentProgram):
    logger = observability.configure(config.log_level, config.log_file_template)
    try:
        await _validate_mcp_endpoint("NVDA", config.nvda_mcp_url)
        await _validate_mcp_endpoint("Chrome DevTools", config.devtools_mcp_url)
        selected_tasks = select_cli_tasks(config)
        if not selected_tasks:
            selected_tasks = await _discover_tasks(config)
        task = _program_task(selected_tasks[0], config)
        observability.navigating()
        observability.info(
            "run.started",
            program_id=program.id,
            url=task["url"],
            goal=task["goal"],
            model=config.model,
            nvda_max_steps=config.nvda_max_steps,
            log_file=str(logger.log_file_path) if logger.log_file_path else None,
        )
        write_started_metadata(config, program, logger.run_id)
        local_tools = [make_verdict_tool(), make_barrier_tool()]
        async with Client(config.nvda_mcp_url) as nvda_session:
            mcp_tools = await register_mcp_tools(nvda_session)
            llm = OpenaiLlmClient(
                config.openai_base_url,
                config.openai_api_key,
                [*local_tools, *mcp_tools],
                additional_headers_for(config.openai_base_url),
            )
            navigator = McpNvdaNavigator(nvda_session)
            await navigator.open(task["url"])
            result = await program.run(
                RunContext(
                    task=task,
                    model=config.model,
                    max_steps=config.nvda_max_steps,
                    trajectory_path=config.trajectory_path,
                    llm=llm,
                    navigator=navigator,
                    run_id=logger.run_id,
                )
            )
            write_result(result, program, logger.run_id)
            observability.result(
                str(result["verdict"]["status"]), result["verdict"]["barriers"]
            )
            observability.info(
                "run.finished",
                status=str(result["verdict"]["status"]),
                barrier_count=len(result["verdict"]["barriers"]),
            )
            return result
    except Exception as exc:
        observability.error("run.failed", error=repr(exc))
        raise
    finally:
        observability.close()


def _program_task(selected_task: WorkflowTask, config: RunConfig) -> Task:
    task: Task = {"url": selected_task["url"], "goal": selected_task["description"]}
    if config.task is not None and "success_hint" in config.task:
        task["success_hint"] = config.task["success_hint"]
    return task


async def _discover_tasks(config: RunConfig) -> list[WorkflowTask]:
    async with Client(config.devtools_mcp_url) as devtools_session:
        devtools_tools = await register_mcp_tools(devtools_session)
        llm = OpenaiLlmClient(
            config.openai_base_url,
            config.openai_api_key,
            [
                *tools_for_phase(WorkflowPhase.DISCOVERY, [], devtools_tools),
                make_discovery_completion_tool(),
            ],
            additional_headers_for(config.openai_base_url),
        )
        return await discover_tasks(config, llm)