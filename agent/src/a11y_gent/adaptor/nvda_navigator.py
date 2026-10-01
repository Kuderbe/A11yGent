"""Load the task page through the NVDA session before the agent loop starts.

The agent must begin with NVDA focused on the task page. Opening Edge through
the same NVDA input session creates the foreground event NVDA follows, unlike
programmatic browser navigation from a separate process.
"""

import asyncio
from typing import Any, Protocol

_LOAD_TIMEOUT_SECONDS = 10
_POLL_INTERVAL_SECONDS = 0.1
_EDGE_EXECUTABLE = r"C:\PROGRA~2\Microsoft\Edge\Application\msedge.exe"
_RUN_DIALOG_SETTLE_SECONDS = 0.8
_TYPE_DELAY_MS = 15


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
        await self._session.call_tool("clear_speech_log", {})
        await self._session.call_tool("send_key", {"gesture": "windows+r"})
        await asyncio.sleep(_RUN_DIALOG_SETTLE_SECONDS)
        await self._session.call_tool("send_key", {"gesture": "control+a"})
        await self._session.call_tool(
            "type_text",
            {"text": f"{_EDGE_EXECUTABLE} {url}", "delay_ms": _TYPE_DELAY_MS},
        )
        await self._session.call_tool("send_key", {"gesture": "enter"})
        await self._wait_for_load()
        await self._session.call_tool("send_key", {"gesture": "control+home"})

    async def _wait_for_load(self) -> None:
        elapsed = 0.0
        while elapsed < self._load_timeout_seconds:
            result = await self._session.call_tool("get_speech_log", {"limit": 20})
            if "Loading complete" in _result_text(result):
                return
            await asyncio.sleep(self._poll_interval_seconds)
            elapsed += self._poll_interval_seconds
        raise TimeoutError("NVDA did not announce that the task page finished loading")


def _result_text(result: Any) -> str:
    """Return MCP text blocks as one string for setup-state inspection."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content", [])
    return "\n".join(
        getattr(block, "text", block.get("text", "") if isinstance(block, dict) else "")
        for block in content or []
    )