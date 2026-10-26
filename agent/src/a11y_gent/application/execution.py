"""Shared infrastructure lifecycle around an agent program."""

from a11y_gent import observability
from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.nvda_navigator import McpNvdaNavigator
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.application.artifacts import write_result, write_started_metadata
from a11y_gent.application.program import AgentProgram, RunContext
from a11y_gent.config import RunConfig
from a11y_gent.main_support import additional_headers_for
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.verdict import make_verdict_tool
from mcp import Client


async def execute(config: RunConfig, program: AgentProgram):
    logger = observability.configure(config.log_level, config.log_file_template)
    observability.navigating()
    observability.info(
        "run.started",
        program_id=program.id,
        url=config.task["url"],
        goal=config.task["goal"],
        model=config.model,
        nvda_max_steps=config.nvda_max_steps,
        log_file=str(logger.log_file_path) if logger.log_file_path else None,
    )
    write_started_metadata(config, program, logger.run_id)
    try:
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
            await navigator.open(config.task["url"])
            result = await program.run(
                RunContext(
                    task=config.task,
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