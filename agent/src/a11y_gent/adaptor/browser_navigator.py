"""Setup-only browser control: load the task URL before the agent starts.

The agent experiences the page exclusively through NVDA; navigation is setup,
not part of the screen-reader profile. So the browser MCP session lives here and
is never registered as an agent tool -- the model cannot see or call it.

:class:`BrowserNavigator` is the narrow interface the runner depends on;
:class:`McpBrowserNavigator` drives a Chrome DevTools MCP session to open a URL
via its ``new_page`` tool (which creates a page for the URL without needing a
pre-existing page id).
"""

from typing import Any, Protocol

_NEW_PAGE_TOOL = "new_page"


class BrowserNavigator(Protocol):
    async def open(self, url: str) -> None:
        """Load ``url`` in the browser the agent will read through NVDA."""


class McpBrowserNavigator:
    """Open a URL via a setup-only Chrome DevTools MCP session."""

    def __init__(self, session: Any):
        self._session = session

    async def open(self, url: str) -> None:
        await self._session.call_tool(_NEW_PAGE_TOOL, {"url": url})

