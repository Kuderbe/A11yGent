"""Tests for optional LLM request headers and OpenCode session selection.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_openai_headers
"""

from uuid import UUID

from a11y_gent.main_support import additional_headers_for
from a11y_gent.adaptor import openai_llm_client as client_module
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient


class _RecordingAsyncOpenAI:
    last_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def _construct_client(additional_headers=None):
    original = client_module.AsyncOpenAI
    client_module.AsyncOpenAI = _RecordingAsyncOpenAI
    try:
        if additional_headers is None:
            OpenaiLlmClient("https://example.test/v1", "key", [])
        else:
            OpenaiLlmClient("https://example.test/v1", "key", [], additional_headers)
        return _RecordingAsyncOpenAI.last_kwargs
    finally:
        client_module.AsyncOpenAI = original


def test_client_passes_additional_headers_to_openai_client():
    headers = {"x-example": "value"}

    kwargs = _construct_client(headers)

    assert kwargs["default_headers"] == headers


def test_client_uses_empty_headers_by_default():
    kwargs = _construct_client()

    assert kwargs["default_headers"] == {}


def test_opencode_root_domain_gets_a_session_header():
    headers = additional_headers_for("https://opencode.ai/v1")

    assert set(headers) == {"x-opencode-session"}
    UUID(headers["x-opencode-session"])


def test_opencode_subdomain_gets_a_session_header():
    headers = additional_headers_for("https://api.opencode.ai/v1")

    assert set(headers) == {"x-opencode-session"}
    UUID(headers["x-opencode-session"])


def test_non_opencode_domains_get_empty_additional_headers():
    for base_url in (
        "https://api.openai.com/v1",
        "https://opencode.ai.example.org/v1",
        "https://example.org/opencode.ai/v1",
        "http://localhost:6655/v1",
    ):
        assert additional_headers_for(base_url) == {}


def test_each_opencode_session_header_is_unique():
    first = additional_headers_for("https://opencode.ai/v1")
    second = additional_headers_for("https://opencode.ai/v1")

    assert first["x-opencode-session"] != second["x-opencode-session"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
