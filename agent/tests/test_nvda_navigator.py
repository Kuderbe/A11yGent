"""Tests for the NVDA-based task-page setup navigator.

Offline, no NVDA/network: a fake MCP session records setup calls and returns a
loading-complete observation. The navigator must open Edge through NVDA and put
the browse cursor at the document start before the agent loop begins.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_nvda_navigator
"""

import asyncio
import logging

from a11y_gent.adaptor.nvda_navigator import McpNvdaNavigator


class _TextBlock:
    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text):
        self.content = [_TextBlock(text)]


class _FakeSession:
    def __init__(self, speech="Loading complete"):
        self.calls = []
        self._speech = speech

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_speech_log":
            return _Result(self._speech)
        return _Result("")


def test_open_launches_edge_waits_for_load_and_moves_to_document_start():
    session = _FakeSession()
    navigator = McpNvdaNavigator(
        session,
        load_timeout_seconds=0.01,
        poll_interval_seconds=0.001,
    )

    asyncio.run(navigator.open("http://example.test/page"))

    assert session.calls == [
        ("clear_speech_log", {}),
        ("send_key", {"gesture": "windows+r"}),
        ("send_key", {"gesture": "control+a"}),
        (
            "type_text",
            {
                "text": (
                    "C:\\PROGRA~2\\Microsoft\\Edge\\Application\\msedge.exe --new-window "
                    "http://example.test/page"
                ),
                "delay_ms": 15,
            },
        ),
        ("send_key", {"gesture": "enter"}),
        ("get_speech_log", {"limit": 20}),
        ("send_key", {"gesture": "control+home"}),
    ]


def test_open_continues_with_warning_without_load_complete():
    session = _FakeSession(speech="Loading page")
    navigator = McpNvdaNavigator(
        session,
        load_timeout_seconds=0.01,
        poll_interval_seconds=0.001,
    )

    logger = logging.getLogger("a11y_gent.adaptor.nvda_navigator")
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    logger.addHandler(handler)
    try:
        asyncio.run(navigator.open("http://example.test/page"))
    finally:
        logger.removeHandler(handler)

    assert any(record.levelno == logging.WARNING for record in records)
    assert session.calls[-1] == ("send_key", {"gesture": "control+home"})


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()