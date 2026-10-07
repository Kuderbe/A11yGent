"""Serialise the agent trajectory to JSON Lines.

The message history is the trajectory: this module projects each message onto a
run phase and its standard chat role before writing JSON Lines. No separate
per-step model is maintained.
"""

from __future__ import annotations

import json
from typing import Iterable

from a11y_gent.model.message import Message, MessageOrigin


def classify_phase(message: Message) -> str:
    """Return the run phase of ``message``.

    - ``"act"``     - an assistant message that issued tool call(s).
    - ``"think"``   - an assistant message with no tool calls (reasoning).
    - ``"observe"`` - a tool-result message.
    - ``"context"`` - system or user framing/task messages.
    """
    origin = message["origin"]
    if origin == MessageOrigin.ASSISTANT:
        return "act" if message.get("tool_calls") else "think"
    if origin == MessageOrigin.TOOL:
        return "observe"
    return "context"


def to_records(history: Iterable[Message]) -> list[dict]:
    """Project a message history into serialisable trajectory records."""
    records: list[dict] = []
    for index, message in enumerate(history):
        record: dict = {
            "index": index,
            "phase": classify_phase(message),
            "message_role": str(message["origin"]),
            "name": message.get("name", ""),
            "content": message.get("content", ""),
        }

        tool_calls = message.get("tool_calls")
        if tool_calls:
            record["tool_calls"] = [
                {
                    "id": call["id"],
                    "tool": call["tool"]["name"],
                    "arguments": call["arguments"],
                }
                for call in tool_calls
            ]

        reference_id = message.get("reference_id")
        if reference_id is not None:
            record["reference_id"] = reference_id

        records.append(record)

    return records


def write_jsonl(history: Iterable[Message], path: str) -> None:
    """Write the trajectory for ``history`` to ``path`` as JSON Lines."""
    records = to_records(history)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
