"""Write nonfatal run events to stderr and, optionally, a template file."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4


class LogLevel(StrEnum):
    MINIMAL = "minimal"
    INFO = "info"
    VERBOSE = "verbose"
    DEBUG = "debug"


class RunLogger:
    """Emit run events without allowing logging failures to stop a run."""

    def __init__(
        self,
        level: LogLevel = LogLevel.INFO,
        log_file_template: str | None = None,
        stderr: TextIO | None = None,
    ):
        self.level = level
        self.run_id = str(uuid4())
        self._stderr = stderr or sys.stderr
        self._file: TextIO | None = None
        self.log_file_path: Path | None = None
        if log_file_template is not None:
            self._open_file(log_file_template)

    def info(self, event: str, **fields: Any) -> None:
        self._emit("info", event, fields)

    def verbose(self, event: str, **fields: Any) -> None:
        self._emit("verbose", event, fields)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit("debug", event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit("warning", event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("error", event, fields)

    def navigating(self) -> None:
        self._transcript("Navigating to Application...\n")

    def reason(self, content: str) -> None:
        self._transcript(f"Reason: {self._transcript_value(content)}\n")

    def act(self, tool: str, arguments: dict[str, Any]) -> None:
        self._transcript(f"Act: {self._format_action(tool, arguments)}\n")

    def observe(self, content: str) -> None:
        self._transcript(f"Observe: {self._transcript_value(content)}\n")

    def result(self, status: str, barriers: list[dict[str, Any]]) -> None:
        if self.level is not LogLevel.MINIMAL:
            return
        lines = [f"Result: {status.replace('_', ' ').upper()}\n", "Found barriers:\n"]
        if barriers:
            lines.extend(f"- {barrier['description']}\n" for barrier in barriers)
        else:
            lines.append("- None\n")
        self._write_all("".join(lines))

    def close(self) -> None:
        if self._file is None:
            return
        try:
            self._file.close()
        except OSError:
            pass
        self._file = None

    def _open_file(self, template: str) -> None:
        path = Path(self._resolve_template(template))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8")
            self.log_file_path = path
        except OSError as exc:
            self._write_stderr(
                f"[a11y-gent WARNING] log.file_unavailable path={path!s} error={exc!s}\n"
            )

    def _resolve_template(self, template: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        return template.replace("<TIMESTAMP>", timestamp).replace("<RUN_ID>", self.run_id)

    def _emit(self, severity: str, event: str, fields: dict[str, Any]) -> None:
        if not self._is_enabled(severity):
            return
        try:
            record = {
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "level": severity,
                "event": event,
                "run_id": self.run_id,
                **fields,
            }
            line = self._format(record)
            self._write_stderr(line)
            self._write_file(line)
        except (TypeError, ValueError, OSError, UnicodeError):
            self._write_stderr("[a11y-gent WARNING] log.event_unavailable\n")

    def _transcript(self, line: str) -> None:
        if self.level is LogLevel.MINIMAL:
            self._write_all(line)

    @staticmethod
    def _transcript_value(value: str) -> str:
        return value.replace("\n", " ").strip()

    @staticmethod
    def _format_action(tool: str, arguments: dict[str, Any]) -> str:
        if tool == "send_key" and set(arguments) == {"gesture"}:
            return f"SendKeys: {arguments['gesture']}"
        if tool == "send_keys" and set(arguments).issubset({"gestures", "delay_ms"}):
            gestures = arguments.get("gestures", [])
            return f"SendKeys: {', '.join(str(gesture) for gesture in gestures)}"
        if tool == "type_text" and "text" in arguments:
            return f"TypeText: {arguments['text']}"
        return f"{tool}: {json.dumps(arguments, ensure_ascii=True, default=str, separators=(',', ':'))}"

    def _is_enabled(self, severity: str) -> bool:
        if severity in ("warning", "error"):
            return True
        if self.level is LogLevel.DEBUG:
            return severity in ("info", "debug")
        if self.level is LogLevel.VERBOSE:
            return severity in ("info", "verbose")
        if self.level is LogLevel.MINIMAL:
            return False
        return severity == "info"

    def _format(self, record: dict[str, Any]) -> str:
        if self.level is LogLevel.DEBUG:
            return json.dumps(record, ensure_ascii=True, default=str, separators=(",", ":")) + "\n"
        details = " ".join(
            f"{key}={self._human_value(value)}"
            for key, value in record.items()
            if key not in {"timestamp", "level", "event", "run_id"}
        )
        suffix = f" {details}" if details else ""
        return f"[{record['timestamp']}] {record['level'].upper()} {record['event']}{suffix}\n"

    @staticmethod
    def _human_value(value: Any) -> str:
        if isinstance(value, str):
            return value.replace("\n", "\\n")
        return json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":"))

    def _write_stderr(self, line: str) -> None:
        try:
            self._stderr.write(line.encode("ascii", "backslashreplace").decode("ascii"))
            self._stderr.flush()
        except (OSError, UnicodeError):
            pass

    def _write_all(self, line: str) -> None:
        self._write_stderr(line)
        self._write_file(line)

    def _write_file(self, line: str) -> None:
        if self._file is None:
            return
        try:
            self._file.write(line)
            self._file.flush()
        except (OSError, UnicodeError):
            self.close()


_logger = RunLogger()


def configure(level: LogLevel, log_file_template: str | None = None) -> RunLogger:
    global _logger
    _logger.close()
    _logger = RunLogger(level, log_file_template)
    return _logger


def close() -> None:
    _logger.close()


def info(event: str, **fields: Any) -> None:
    _logger.info(event, **fields)


def verbose(event: str, **fields: Any) -> None:
    _logger.verbose(event, **fields)


def debug(event: str, **fields: Any) -> None:
    _logger.debug(event, **fields)


def warning(event: str, **fields: Any) -> None:
    _logger.warning(event, **fields)


def error(event: str, **fields: Any) -> None:
    _logger.error(event, **fields)


def navigating() -> None:
    _logger.navigating()


def reason(content: str) -> None:
    _logger.reason(content)


def act(tool: str, arguments: dict[str, Any]) -> None:
    _logger.act(tool, arguments)


def observe(content: str) -> None:
    _logger.observe(content)


def result(status: str, barriers: list[dict[str, Any]]) -> None:
    _logger.result(status, barriers)