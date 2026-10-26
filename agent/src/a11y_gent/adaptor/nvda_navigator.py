"""Load the task page through the NVDA session before the agent loop starts.

The agent must begin with NVDA focused on the task page. Opening Edge through
the same NVDA input session creates the foreground event NVDA follows, unlike
programmatic browser navigation from a separate process.
"""

import asyncio
import logging
from typing import Any, Protocol

from a11y_gent import observability

_LOAD_TIMEOUT_SECONDS = 10
_POLL_INTERVAL_SECONDS = 0.1
_EDGE_EXECUTABLE = r"C:\PROGRA~2\Microsoft\Edge\Application\msedge.exe"
_RUN_DIALOG_SETTLE_SECONDS = 0.8
_TYPE_DELAY_MS = 15

logger = logging.getLogger(__name__)


class TaskNavigator(Protocol):
    async def open(self, url: str) -> None:
        """Load ``url`` and leave NVDA at the start of its document."""


class McpNvdaNavigator:
    """Open the task URL using the existing NVDA MCP session."""

    def __init__(
        self,
        session: Any,
        load_timeout_seconds: float = _LOAD_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
    ):
        self._session = session
        self._load_timeout_seconds = load_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    async def open(self, url: str) -> None:
        observability.verbose("navigation.started", url=url)
        observability.debug("navigation.started", url=url)
        await self._call_tool("clear_speech_log", {})
        await self._call_tool("send_key", {"gesture": "windows+r"})
        await asyncio.sleep(_RUN_DIALOG_SETTLE_SECONDS)
        await self._call_tool("send_key", {"gesture": "control+a"})
        await self._call_tool(
            "type_text",
            {"text": f"{_EDGE_EXECUTABLE} --new-window {url}", "delay_ms": _TYPE_DELAY_MS},
        )
        await self._call_tool("send_key", {"gesture": "enter"})
        await self._wait_for_load()
        await self._call_tool("send_key", {"gesture": "control+home"})
        observability.info("navigation.completed", url=url)

    async def _wait_for_load(self) -> None:
        elapsed = 0.0
        while elapsed < self._load_timeout_seconds:
            result = await self._call_tool("get_speech_log", {"limit": 20})
            if "Loading complete" in _result_text(result):
                return
            await asyncio.sleep(self._poll_interval_seconds)
            elapsed += self._poll_interval_seconds
        # NVDA sometimes omits this announcement; investigate why separately.
        logger.warning(
            "NVDA did not announce that the task page finished loading within %ss; "
            "continuing with the page as it is",
            self._load_timeout_seconds,
        )
        observability.warning(
            "navigation.load_timeout", timeout_seconds=self._load_timeout_seconds
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        observability.verbose("navigation.mcp_call", tool=name, arguments=arguments)
        observability.debug("navigation.mcp_call", tool=name, arguments=arguments)
        result = await self._session.call_tool(name, arguments)
        observability.debug("navigation.mcp_result", tool=name, result=str(result))
        return result


def _result_text(result: Any) -> str:
    """Return MCP text blocks as one string for setup-state inspection."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content", [])
    return "\n".join(
        getattr(block, "text", block.get("text", "") if isinstance(block, dict) else "")
        for block in content or []
    )