"""Tests for the setup-only browser navigator (a11y_gent.adaptor.browser_navigator).

Offline, no browser/network: a fake MCP session records the tool call the
navigator makes, verifying it uses the Chrome DevTools new_page tool with the
URL.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_browser_navigator
"""

import asyncio

from a11y_gent.adaptor.browser_navigator import McpBrowserNavigator


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))


def test_open_calls_new_page_with_url():
    session = _FakeSession()
    navigator = McpBrowserNavigator(session)

    asyncio.run(navigator.open("http://example.test/page"))

    assert session.calls == [("new_page", {"url": "http://example.test/page"})]



def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
