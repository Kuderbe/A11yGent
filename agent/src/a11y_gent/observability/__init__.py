"""Structured run logging for human inspection and machine analysis."""

from a11y_gent.observability.events import (
    LogLevel,
    act,
    close,
    configure,
    debug,
    error,
    info,
    navigating,
    observe,
    reason,
    result,
    verbose,
    warning,
)

__all__ = [
    "LogLevel", "act", "close", "configure", "debug", "error", "info",
    "navigating", "observe", "reason", "result", "verbose", "warning",
]