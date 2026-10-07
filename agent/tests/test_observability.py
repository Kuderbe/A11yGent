"""Tests for stderr and optional file logging.

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_observability
"""

import io
import json
import tempfile
from pathlib import Path

from a11y_gent.observability.events import LogLevel, RunLogger


def test_info_omits_verbose_and_debug_events():
    stderr = io.StringIO()
    logger = RunLogger(LogLevel.INFO, stderr=stderr)

    logger.info("run.started")
    logger.verbose("node.started")
    logger.debug("llm.request")

    output = stderr.getvalue()
    assert "run.started" in output
    assert "node.started" not in output
    assert "llm.request" not in output


def test_verbose_writes_human_readable_thinking():
    stderr = io.StringIO()
    logger = RunLogger(LogLevel.VERBOSE, stderr=stderr)

    logger.verbose("node.completed", thinking="inspect → button")

    output = stderr.getvalue()
    assert "node.completed" in output
    assert "inspect \\u2192 button" in output


def test_debug_writes_parseable_ascii_json():
    stderr = io.StringIO()
    logger = RunLogger(LogLevel.DEBUG, stderr=stderr)

    logger.debug("llm.response", content="a→ä")

    line = stderr.getvalue()
    assert line.isascii()
    record = json.loads(line)
    assert record["event"] == "llm.response"
    assert record["content"] == "a→ä"


def test_log_file_template_replaces_timestamp_and_run_id():
    with tempfile.TemporaryDirectory() as tmp:
        stderr = io.StringIO()
        template = str(Path(tmp) / "nested" / "run-<TIMESTAMP>-<RUN_ID>.log")
        logger = RunLogger(LogLevel.INFO, template, stderr)
        logger.info("run.started")
        logger.close()

        assert logger.log_file_path is not None
        assert "<TIMESTAMP>" not in str(logger.log_file_path)
        assert "<RUN_ID>" not in str(logger.log_file_path)
        assert logger.run_id in logger.log_file_path.name
        assert "T" in logger.log_file_path.name
        assert ":" not in logger.log_file_path.name
        assert "run.started" in logger.log_file_path.read_text(encoding="utf-8")


def test_file_failure_does_not_stop_stderr_logging():
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / "not-a-directory"
        parent.write_text("file", encoding="utf-8")
        stderr = io.StringIO()
        logger = RunLogger(LogLevel.INFO, str(parent / "log.txt"), stderr)

        logger.info("run.started")

        assert "log.file_unavailable" in stderr.getvalue()
        assert "run.started" in stderr.getvalue()


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()