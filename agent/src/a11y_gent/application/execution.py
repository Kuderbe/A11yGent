"""Shared infrastructure lifecycle around an agent program."""

from pathlib import Path

from a11y_gent import observability
from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.nvda_navigator import McpNvdaNavigator
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.application.artifacts import write_result, write_started_metadata
from a11y_gent.application.program import AgentProgram, RunContext
from a11y_gent.config import RunConfig
from a11y_gent.main_support import additional_headers_for
from a11y_gent.model.assessment_report import AssessmentReport
from a11y_gent.model.task import Task
from a11y_gent.model.workflow import DiscoveryResult, WorkflowPhase, WorkflowTask
from a11y_gent.prompts import (
    make_discovery_completion_tool,
    make_report_enrichment_completion_tool,
    make_retrospective_completion_tool,
    make_solve_task_completion_tool,
    make_verify_completion_tool,
)
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
        if getattr(program, "uses_phased_workflow", False):
            return await _execute_phased(config, program, logger.run_id)
        selected_tasks = select_cli_tasks(config)
        if not selected_tasks:
            selected_tasks = await _discover_tasks(config, logger.run_id)
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


async def _execute_phased(config: RunConfig, program: AgentProgram, run_id: str) -> AssessmentReport:
    resuming = config.resume_path is not None and Path(config.resume_path).with_suffix(".metadata.json").exists()
    selected_tasks = None if resuming else select_cli_tasks(config)
    discovery_incomplete = False
    async with Client(config.nvda_mcp_url) as nvda_session, Client(config.devtools_mcp_url) as devtools_session:
        nvda_tools = await register_mcp_tools(nvda_session)
        devtools_tools = await register_mcp_tools(devtools_session)
        if selected_tasks == []:
            discovery = await _discover_tasks_with_tools(config, devtools_tools)
            selected_tasks = discovery.tasks
            discovery_incomplete = discovery.incomplete
        task = (
            _program_task(selected_tasks[0], config)
            if selected_tasks
            else {"url": config.application_url, "goal": "Resume assessment"}
        )
        observability.navigating()
        observability.info(
            "run.started",
            program_id=program.id,
            url=task["url"],
            goal=task["goal"],
            model=config.model,
            nvda_max_steps=config.nvda_max_steps,
        )
        write_started_metadata(config, program, run_id)
        report = await program.run(
            RunContext(
                task, config.model, config.nvda_max_steps, config.trajectory_path,
                _llm(config, [*nvda_tools, make_solve_task_completion_tool()]), McpNvdaNavigator(nvda_session), run_id,
                workflow_tasks=selected_tasks, discovery_incomplete=discovery_incomplete,
                discovery_max_steps=config.discovery_max_steps, report_path=config.report_path,
                solve_llm=_llm(config, [*nvda_tools, make_solve_task_completion_tool()]),
                retrospective_llm=_llm(config, [make_retrospective_completion_tool()]),
                verification_llm=_llm(config, [*nvda_tools, make_verify_completion_tool()]),
                devtools_llm=_llm(config, [*devtools_tools, make_report_enrichment_completion_tool()]),
                nvda_tools=nvda_tools, devtools_tools=devtools_tools, workflow_config=config,
            )
        )
    observability.info("run.finished", report_path=config.report_path)
    return report


def _program_task(selected_task: WorkflowTask, config: RunConfig) -> Task:
    task: Task = {"url": selected_task["url"], "goal": selected_task["description"]}
    if config.task is not None and "success_hint" in config.task:
        task["success_hint"] = config.task["success_hint"]
    return task


async def _discover_tasks(config: RunConfig, run_id: str) -> list[WorkflowTask]:
    async with Client(config.devtools_mcp_url) as devtools_session:
        devtools_tools = await register_mcp_tools(devtools_session)
        discovery = await _discover_tasks_with_tools(config, devtools_tools)
        return discovery.tasks


async def _discover_tasks_with_tools(config: RunConfig, devtools_tools: list) -> DiscoveryResult:
    tools = [*tools_for_phase(WorkflowPhase.DISCOVERY, [], devtools_tools), make_discovery_completion_tool()]
    return await discover_tasks(config, _llm(config, tools), tools)


def _llm(config: RunConfig, tools: list):
    return OpenaiLlmClient(
        config.openai_base_url,
        config.openai_api_key,
        tools,
        additional_headers_for(config.openai_base_url),
    )