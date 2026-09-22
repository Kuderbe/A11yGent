"""Serialise the agent trajectory to JSON Lines.

The message history is the trajectory: this module classifies each message as a
reasoning ("think"), action ("act"), or observation turn and writes the run to
a JSON Lines file. No separate per-step model is maintained.
"""

from __future__ import annotations

import json
from typing import Iterable

from a11y_gent.model.message import Message, MessageOrigin


def classify(message: Message) -> str:
    """Return the trajectory role of ``message``.

    - ``"action"``      - an assistant message that issued tool call(s).
    - ``"think"``       - an assistant message with no tool calls (reasoning).
    - ``"observation"`` - a tool-result message.
    - ``"system"`` / ``"user"`` - framing/task messages.
    """
    origin = message["origin"]
    if origin == MessageOrigin.ASSISTANT:
        return "action" if message.get("tool_calls") else "think"
    if origin == MessageOrigin.TOOL:
        return "observation"
    return str(origin)


def to_records(history: Iterable[Message]) -> list[dict]:
    """Project a message history into serialisable trajectory records."""
    records: list[dict] = []
    for index, message in enumerate(history):
        record: dict = {
            "index": index,
            "role": classify(message),
            "origin": str(message["origin"]),
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
