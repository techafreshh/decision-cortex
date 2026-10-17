"""The frozen AG-UI/SSE event schema for the ``POST /ask`` stream.

The web UI (#10) and this backend are built against one hand-rolled schema
(the PRD §6.2 fallback: "hand-rolled SSE with the same event schema"), so the
event names and payload fields below are the contract. Every event is a plain
``dict`` whose ``type`` is one of the constants here; :func:`sse_encode` frames
one as a Server-Sent Events record.

Frozen payloads (field names are snake_case, matching the rest of the API):

- ``RUN_STARTED`` — ``question``, ``scenario``.
- ``TOOL_CALL_START`` — ``tool_call_id``, ``tool_name``.
- ``TOOL_CALL_ARGS`` — ``tool_call_id``, ``delta`` (JSON-encoded arguments).
- ``TOOL_CALL_END`` — ``tool_call_id``.
- ``TOOL_CALL_RESULT`` — ``tool_call_id``, ``result``.
- ``TEXT_MESSAGE_START`` / ``TEXT_MESSAGE_END`` — ``message_id``.
- ``TEXT_MESSAGE_CONTENT`` — ``message_id``, ``delta`` (the sentence),
  ``chips`` (citation chips), ``cited`` (whether the sentence cleared its gate).
- ``CYPHER_PREVIEW`` — ``queries`` (the Cypher strings retrieval actually ran).
- ``LEDGER_UPDATE`` — ``ledger`` (the decision-ledger summary: ``calls``,
  ``cost_usd``, ``total_calls``, ``total_cost_usd``, and ``records`` — this
  run's :class:`~api.llm.LedgerRecord` rows).
- ``FAITHFULNESS_PENDING`` — no extra fields; the async scoring marker.
- ``RUN_FINISHED`` — ``citation_count``, ``claims_total``, ``claims_cited``,
  ``abstention_required``, ``ledger``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

RUN_STARTED = "RUN_STARTED"
TOOL_CALL_START = "TOOL_CALL_START"
TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
TOOL_CALL_END = "TOOL_CALL_END"
TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
CYPHER_PREVIEW = "CYPHER_PREVIEW"
LEDGER_UPDATE = "LEDGER_UPDATE"
FAITHFULNESS_PENDING = "FAITHFULNESS_PENDING"
RUN_FINISHED = "RUN_FINISHED"


def sse_encode(event: Mapping[str, Any]) -> str:
    """Frame ``event`` as one SSE record: ``event:`` line, ``data:`` line, blank."""
    return (
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    )
