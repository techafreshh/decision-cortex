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

``GET /graph/impact/{id}`` and ``GET /timeline`` (plus its ``?tour=async_await``
form) back the web Impact Explorer and Timeline (PRD §7.1); ``POST /exports/report``
and ``POST /exports/graph`` download a Markdown report or the impact subgraph
(PRD §10). All four are pure graph reads — no LLM, so they cost nothing.
"""

from collections.abc import Iterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from api.answer import SCENARIOS, ask_events
from api.events import sse_encode
from api.exports import ExportError, export_filename, render_graph, render_report
from api.impact import IMPACT_MAX_DEPTH, build_impact
from api.nodes import node_detail
from api.retrieval import connect_from_env
from api.timeline import build_timeline
from api.tours import build_tour
from api.seed import graph_is_seeded


app = FastAPI(title="Decision Cortex API")


class AskRequest(BaseModel):
    question: str | None = None
    scenario: str | None = None
    mode: Literal["free", "scripted"] = "free"


class ReportRequest(BaseModel):
    node_id: str | None = None
    scenario: str | None = None


class GraphExportRequest(BaseModel):
    node_id: str
    depth: int = IMPACT_MAX_DEPTH


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "seeded": graph_is_seeded(connect_from_env())}


@app.get("/node/{node_id}")
def node(node_id: str) -> dict[str, Any]:
    detail = node_detail(connect_from_env(), node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id!r}")
    return detail


@app.get("/graph/impact/{node_id}")
def impact(node_id: str, depth: int = IMPACT_MAX_DEPTH) -> dict[str, Any]:
    payload = build_impact(connect_from_env(), node_id, depth=depth)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id!r}")
    return payload


@app.get("/timeline")
def timeline(
    tour: str | None = None, area: str | None = None, team: str | None = None
) -> dict[str, Any]:
    reader = connect_from_env()
    if tour is not None:
        payload = build_tour(reader, tour)
        if payload is None:
            raise HTTPException(status_code=400, detail=f"unknown tour {tour!r}")
        return payload
    return build_timeline(reader, area=area, team=team)


@app.post("/exports/report")
def export_report(request: ReportRequest) -> Response:
    try:
        markdown = render_report(
            connect_from_env(), node_id=request.node_id, scenario=request.scenario
        )
    except ExportError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    filename = export_filename(node_id=request.node_id, scenario=request.scenario, suffix="md")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/exports/graph")
def export_graph(request: GraphExportRequest) -> JSONResponse:
    try:
        payload = render_graph(connect_from_env(), request.node_id, depth=request.depth)
    except ExportError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    filename = export_filename(node_id=request.node_id, suffix="json")
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
