"""Recover the structured verdict and barriers from the message history.

Both ``report_verdict`` and ``report_barrier`` are no-op sink tools whose
payload lives in their tool-call arguments; this module scans the history and
rebuilds the typed :class:`~a11y_gent.model.verdict.Verdict` and
:class:`~a11y_gent.model.verdict.Barrier` objects from those calls.
"""

from typing import Any, Iterable, Optional

from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.verdict import Barrier, Verdict, VerdictStatus


def _tool_call_args(history: Iterable[Message], tool_name: str) -> list[dict]:
    """Return the arguments of every call to ``tool_name`` in order."""
    calls: list[dict] = []
    for message in history:
        if message["origin"] != MessageOrigin.ASSISTANT:
            continue
        for call in message.get("tool_calls", []) or []:
            if call["tool"]["name"] == tool_name:
                calls.append(call.get("arguments", {}) or {})
    return calls


def extract_barriers(history: Iterable[Message]) -> list[Barrier]:
    """Rebuild the barrier list from ``report_barrier`` tool calls."""
    history = list(history)
    barriers: list[Barrier] = []
    for args in _tool_call_args(history, "report_barrier"):
        barrier: Barrier = {
            "description": str(args.get("description", "")),
            "evidence": str(args.get("evidence", "")),
        }
        wcag = args.get("wcag")
        if wcag is not None:
            barrier["wcag"] = _coerce_wcag(wcag)
        barriers.append(barrier)
    return barriers


def extract_verdict(history: Iterable[Message]) -> Optional[Verdict]:
    """Rebuild the verdict from the ``report_verdict`` call, if any.

    Returns ``None`` if the agent never reported a verdict.
    """
    history = list(history)
    verdict_calls = _tool_call_args(history, "report_verdict")
    if not verdict_calls:
        return None

    args = verdict_calls[-1]
    return Verdict(
        status=_coerce_status(args.get("status")),
        summary=str(args.get("summary", "")),
        barriers=extract_barriers(history),
    )


def _coerce_status(status: Any) -> VerdictStatus:
    try:
        return VerdictStatus(str(status))
    except ValueError:
        # An unexpected status string: treat as failed rather than crash.
        return VerdictStatus.FAILED


def _coerce_wcag(wcag: Any) -> list[str]:
    if isinstance(wcag, str):
        return [wcag]
    if isinstance(wcag, (list, tuple, set)):
        return [str(item) for item in wcag]
    return [str(wcag)]
