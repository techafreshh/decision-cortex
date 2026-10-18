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

``POST /faithfulness`` scores a finished answer's sentences against their cited
evidence with the local HHEM-2.1-Open cross-encoder (:mod:`api.faithfulness`) —
the badge's async post-stream phase. ``GET /verification`` serves the pinned
40-question set; ``POST /verification/run`` executes it through the live answer
pipeline and reports accuracy and abstention correctness (:mod:`api.evaluation`;
real OpenRouter calls, so it refuses politely without a key).
"""

from collections.abc import Iterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from api import evaluation, evidence_text, faithfulness, llm
from api.answer import SCENARIOS, answer_question, ask_events
from api.events import sse_encode
from api.exports import ExportError, export_filename, render_graph, render_report
from api.impact import IMPACT_MAX_DEPTH, build_impact
from api.nodes import node_detail
from api.retrieval import connect_from_env
from api.seed import graph_is_seeded
from api.timeline import build_timeline
from api.tours import build_tour

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


class FaithfulnessClaim(BaseModel):
    sentence: str
    evidence_ids: list[str] = []


class FaithfulnessRequest(BaseModel):
    claims: list[FaithfulnessClaim]


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


@app.post("/faithfulness")
def faithfulness_score(request: FaithfulnessRequest) -> dict[str, Any]:
    """Score a finished answer's claims against their cited evidence text."""
    reader = connect_from_env()
    unique_ids = sorted(
        {eid for claim in request.claims for eid in claim.evidence_ids}
    )
    try:
        scorer = faithfulness.get_scorer()
        texts = evidence_text.resolve_evidence_texts(reader, unique_ids)
        report = faithfulness.score_answer(
            [
                faithfulness.ClaimInput(
                    sentence=claim.sentence, evidence_ids=tuple(claim.evidence_ids)
                )
                for claim in request.claims
            ],
            texts,
            score_fn=scorer,
            threshold=faithfulness.threshold_from_env(),
            model_label=getattr(scorer, "model_id", None),
        )
    except faithfulness.FaithfulnessUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return report.payload()


@app.get("/verification")
def verification() -> dict[str, Any]:
    """The pinned 40-question set, exactly as authored (PRD §10)."""
    try:
        entries = evaluation.load_set()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"verification set unavailable: {error}",
        ) from error
    gold = [entry.raw for entry in entries if entry.type == "gold"]
    no_record = [entry.raw for entry in entries if entry.type == "no_record"]
    return {
        "gold": gold,
        "no_record": no_record,
        "counts": {"gold": len(gold), "no_record": len(no_record)},
    }


@app.post("/verification/run")
def verification_run() -> dict[str, Any]:
    """Execute the pinned set through the live pipeline (real OpenRouter calls).

    Owner-dispatched: the eval-run workflow provides the spend-capped key.
    Without a key this refuses with 503 so the offline path can never burn
    budget; with one, the report carries the run's own ledger rows and cost.
    """
    try:
        evaluation.require_key()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        entries = evaluation.load_set()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"verification set unavailable: {error}",
        ) from error
    with llm.collect_ledger() as records:
        result = evaluation.run_set(entries, answer_question)
    payload = result.payload()
    payload["calls"] = len(records)
    payload["cost_usd"] = round(sum(record.cost_usd for record in records), 6)
    payload["total_calls"] = len(llm.ledger_records())
    payload["total_cost_usd"] = round(llm.ledger_total_cost_usd(), 6)
    return payload


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
