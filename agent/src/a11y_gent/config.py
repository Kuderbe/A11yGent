"""Run configuration: every parameter one agent run needs, in one place.

:class:`RunConfig` is an immutable bundle the CLI builds once and hands to
:class:`a11y_gent.runner.AgentRunner`. Keeping it separate from the CLI means
tests can construct a config directly, without environment variables or
argument parsing.
"""

from dataclasses import dataclass
from typing import Literal

from a11y_gent.model.task import Task
from mcp import StdioServerParameters

_CHROME_DEVTOOLS_PACKAGE = "chrome-devtools-mcp@latest"


@dataclass(frozen=True)
class BrowserMcpSpec:
    """How to reach the setup-only browser MCP.

    ``mode="stdio"`` launches the Chrome DevTools MCP as an ``npx`` subprocess
    (optionally attaching to a running Chrome via ``chrome_url``, or picking a
    channel/executable). ``mode="url"`` connects to an MCP already served over
    Streamable HTTP at ``url``.
    """

    mode: Literal["stdio", "url"] = "stdio"
    # url mode: the Streamable-HTTP endpoint of an already-running browser MCP.
    url: str | None = None
    # stdio mode: address of a separately-started, debuggable Chrome for the
    # spawned MCP to attach to (its --browser-url), instead of launching its
    # own Chrome. This is the browser process, not the MCP server.
    chrome_url: str | None = None
    channel: str | None = None
    executable: str | None = None


@dataclass(frozen=True)
class RunConfig:
    task: Task
    model: str
    openai_base_url: str
    openai_api_key: str
    nvda_mcp_url: str
    browser_mcp: BrowserMcpSpec
    max_steps: int
    trajectory_path: str


def build_task(url: str, goal: str, success_hint: str | None) -> Task:
    """Build the :class:`Task` from the user-facing inputs."""
    task: Task = {"url": url, "goal": goal}
    if success_hint is not None:
        task["success_hint"] = success_hint
    return task


def build_browser_client_target(
    spec: BrowserMcpSpec,
) -> str | StdioServerParameters:
    """Turn a :class:`BrowserMcpSpec` into an ``mcp.Client`` target.

    ``url`` mode returns the URL string (Streamable HTTP). ``stdio`` mode
    returns ``StdioServerParameters`` launching the Chrome DevTools MCP. The
    browser runs headful (no ``--headless``) because NVDA has to read a real,
    visible window.
    """
    if spec.mode == "url":
        if not spec.url:
            raise ValueError("browser MCP url mode requires a url")
        return spec.url

    args = ["-y", _CHROME_DEVTOOLS_PACKAGE]
    if spec.chrome_url:
        args.append(f"--browser-url={spec.chrome_url}")
    if spec.channel:
        args.append(f"--channel={spec.channel}")
    if spec.executable:
        args.append(f"--executable-path={spec.executable}")
    return StdioServerParameters(command="npx", args=args)

