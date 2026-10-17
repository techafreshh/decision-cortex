"""Offline tests for the SSE framing of the frozen AG-UI event schema."""

from __future__ import annotations

import json

from api import events


def test_sse_encode_frames_event_and_round_trips() -> None:
    event = {
        "type": events.TEXT_MESSAGE_CONTENT,
        "message_id": "answer",
        "delta": "RFC 200 introduced trait objects.",
        "chips": [{"id": "rfc:200", "label": "Decision", "title": "Trait objects"}],
        "cited": True,
    }

    encoded = events.sse_encode(event)

    assert encoded.startswith(f"event: {events.TEXT_MESSAGE_CONTENT}\n")
    assert encoded.endswith("\n\n")
    lines = encoded.split("\n")
    assert lines[0] == f"event: {events.TEXT_MESSAGE_CONTENT}"
    assert lines[1].startswith("data: ")
    assert json.loads(lines[1].removeprefix("data: ")) == event
    assert lines[2:] == ["", ""]
