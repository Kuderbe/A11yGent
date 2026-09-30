import asyncio
import os
from typing import Optional

import typer
from a11y_gent.adaptor.browser_navigator import McpBrowserNavigator
from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.config import (
    BrowserMcpSpec,
    RunConfig,
    build_browser_client_target,
    build_task,
)
from a11y_gent.runner import AgentRunner
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.verdict import make_verdict_tool
from dotenv import load_dotenv
from mcp import Client

load_dotenv()

app = typer.Typer(add_completion=False, help="Run the A11yGent screen-reader agent on a task.")


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
    browser_mcp_mode: str = typer.Option(
        "stdio",
        envvar="A11Y_GENT_BROWSER_MCP_MODE",
        help="How to reach the setup-only browser MCP: 'stdio' (launch Chrome "
        "DevTools MCP via npx) or 'url' (connect to a running MCP).",
    ),
    browser_mcp_url: Optional[str] = typer.Option(
        None,
        envvar="A11Y_GENT_BROWSER_MCP_URL",
        help="url mode only: Streamable-HTTP endpoint of a running browser MCP.",
    ),
    browser_chrome_url: Optional[str] = typer.Option(
        None,
        envvar="A11Y_GENT_BROWSER_CHROME_URL",
        help="stdio mode only: attach the MCP to a running debuggable Chrome "
        "(e.g. http://127.0.0.1:9222) instead of launching its own.",
    ),
    browser_channel: Optional[str] = typer.Option(
        None,
        help="stdio mode only: Chrome channel for the MCP (e.g. stable, canary).",
    ),
    browser_executable: Optional[str] = typer.Option(
        None,
        help="stdio mode only: path to a custom Chrome/Edge executable.",
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
        browser_mcp=BrowserMcpSpec(
            mode=browser_mcp_mode,
            url=browser_mcp_url,
            chrome_url=browser_chrome_url,
            channel=browser_channel,
            executable=browser_executable,
        ),
        max_steps=max_steps,
        trajectory_path=out,
    )
    result = asyncio.run(_run(config))
    print("Verdict:", result["verdict"])


async def _run(config: RunConfig):
    local_tools = [make_verdict_tool(), make_barrier_tool()]

    browser_target = build_browser_client_target(config.browser_mcp)

    # Two MCP sessions: the NVDA bridge supplies the agent's tools; the browser
    # session is setup-only (loads the page) and is never given to the model.
    async with Client(config.nvda_mcp_url) as nvda_session, \
            Client(browser_target) as browser_session:
        mcp_tools = await register_mcp_tools(nvda_session)
        tools = [*local_tools, *mcp_tools]

        llm = OpenaiLlmClient(
            config.openai_base_url, config.openai_api_key, tools
        )
        navigator = McpBrowserNavigator(browser_session)

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








