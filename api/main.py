"""FastAPI service for Decision Cortex.

Liveness is deliberately decoupled from FalkorDB availability: ``/healthz``
answers 200 from the process alone, so the API boots (and the verification
container can probe it) with no database reachable. The seed status is a live
count of the loaded Decisions and their edges (``api.seed.graph_is_seeded``)
reported honestly in the body instead of gating the response — an unreachable
database is ``seeded: false``, not a failed probe.

``POST /ask`` streams the AG-UI event sequence (PRD §10) as Server-Sent
Events: ``RUN_STARTED`` → tool-call events → ``TEXT_MESSAGE_CONTENT`` deltas
with citation chips → custom ``cypher_preview``/``ledger_update``/
``faithfulness_pending`` → ``RUN_FINISHED``. ``scenario`` selects a deterministic
scripted question (and its cached answer); ``question`` is the free-chat path.

``GET /node/{id}`` resolves a citation-chip id to its graph node for the web
``SourcePanel`` (:mod:`api.nodes`).
"""

from collections.abc import Iterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.answer import SCENARIOS, ask_events
from api.events import sse_encode
from api.nodes import node_detail
from api.retrieval import connect_from_env
from api.seed import graph_is_seeded

app = FastAPI(title="Decision Cortex API")


class AskRequest(BaseModel):
    question: str | None = None
    scenario: str | None = None
    mode: Literal["free", "scripted"] = "free"


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "seeded": graph_is_seeded(connect_from_env())}


@app.get("/node/{node_id}")
def node(node_id: str) -> dict[str, Any]:
    detail = node_detail(connect_from_env(), node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id!r}")
    return detail


@app.post("/ask")
def ask(request: AskRequest) -> StreamingResponse:
    if request.scenario is not None and request.scenario not in SCENARIOS:
        raise HTTPException(
            status_code=400, detail=f"unknown scenario {request.scenario!r}"
        )
    if request.scenario is None and not (request.question or "").strip():
        raise HTTPException(
            status_code=400, detail="a question or a known scenario is required"
        )
    stream: Iterator[str] = (
        sse_encode(event) for event in ask_events(request.question, request.scenario)
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
