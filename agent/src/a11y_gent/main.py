import asyncio
import os
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

import typer
from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.nvda_navigator import McpNvdaNavigator
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.config import RunConfig, build_task
from a11y_gent.runner import AgentRunner
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.verdict import make_verdict_tool
from dotenv import load_dotenv
from mcp import Client

load_dotenv()

app = typer.Typer(add_completion=False, help="Run the A11yGent screen-reader agent on a task.")


def _additional_headers_for(base_url: str) -> dict[str, str]:
    hostname = urlparse(base_url).hostname
    if hostname is None or not (hostname == "opencode.ai" or hostname.endswith(".opencode.ai")):
        return {}
    return {"x-opencode-session": str(uuid4())}


@app.command()
def run(
    url: str = typer.Option(..., help="URL of the page/app under test."),
    goal: str = typer.Option(..., help="The user story / task to attempt."),
    success_hint: Optional[str] = typer.Option(
        None, help="Optional note describing what 'done' looks like."
    ),
    model: str = typer.Option(
        "gpt-5-mini", envvar="A11Y_GENT_MODEL", help="LLM model name."
    ),
    nvda_mcp_url: str = typer.Option(
        "http://192.168.64.4:8765/mcp",
        envvar="A11Y_GENT_MCP_URL",
        help="URL of the NVDA MCP bridge (its tools drive the agent).",
    ),
    max_steps: int = typer.Option(
        30, help="Safety net: stop after this many reasoning steps."
    ),
    out: str = typer.Option(
        "trajectory.jsonl", help="Where to write the trajectory JSONL."
    ),
) -> None:
    """Attempt GOAL on URL as a screen-reader user and report a verdict."""
    config = RunConfig(
        task=build_task(url, goal, success_hint),
        model=model,
        openai_base_url=os.environ["A11Y_GENT_OPENAI_BASE_URL"],
        openai_api_key=os.environ["A11Y_GENT_OPENAI_API_KEY"],
        nvda_mcp_url=nvda_mcp_url,
        max_steps=max_steps,
        trajectory_path=out,
    )
    result = asyncio.run(_run(config))
    print("Verdict:", result["verdict"])


async def _run(config: RunConfig):
    local_tools = [make_verdict_tool(), make_barrier_tool()]

    # One persistent NVDA session performs setup and supplies every agent tool.
    async with Client(config.nvda_mcp_url) as nvda_session:
        mcp_tools = await register_mcp_tools(nvda_session)
        tools = [*local_tools, *mcp_tools]

        llm = OpenaiLlmClient(
            config.openai_base_url,
            config.openai_api_key,
            tools,
            _additional_headers_for(config.openai_base_url),
        )
        navigator = McpNvdaNavigator(nvda_session)

        return await AgentRunner(
            llm,
            navigator,
            config.task,
            config.model,
            config.max_steps,
            config.trajectory_path,
        ).run()


def main():
    app()








