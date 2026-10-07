"""Structured run logging for human inspection and machine analysis."""

from a11y_gent.observability.events import (
    LogLevel,
    close,
    configure,
    debug,
    error,
    info,
    verbose,
    warning,
)

__all__ = ["LogLevel", "close", "configure", "debug", "error", "info", "verbose", "warning"]