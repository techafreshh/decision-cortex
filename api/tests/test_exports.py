"""Offline tests for the portable exports (``api/exports.py`` and its routes).

A fake :class:`GraphReader` answers the indexed node lookup and the impact hop,
and the scripted-scenario path is exercised against the real
:data:`api.cache.cache` — so the Markdown report, the impact JSON, the 404/400/
409 error contract, and the download headers are all covered with no graph and
no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import exports, main
from api.answer import AnswerPlan
from api.cache import cache
from api.claim_gate import ClaimVerdict
from api.main import app
from api.retrieval import EvidenceNode


class ExportReader:
    def __init__(
        self,
        *,
        nodes: dict[str, list[Any]] | None = None,
        neighbors: dict[str, list[tuple[Any, ...]]] | None = None,
    ) -> None:
        self.nodes = nodes or {}
        self.neighbors = neighbors or {}

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        if "startNode(r).id" in cypher:
            rows: list[list[Any]] = []
            for origin in params["ids"]:
                for relation, src, dst, neighbor in self.neighbors.get(origin, []):
                    node_id, labels, props = neighbor
                    rows.append([origin, relation, {}, src, dst, node_id, labels, props])
            return rows
        if "MATCH (n:__Entity__ {id: $id})" in cypher:
            row = self.nodes.get(params["id"])
            return [] if row is None else [row]
        raise AssertionError(f"unexpected cypher: {cypher}")


def _reader() -> ExportReader:
    return ExportReader(
        nodes={
            "rfc:2394": [
                ["Decision"],
                {
                    "id": "rfc:2394",
                    "title": "async/await notation",
                    "status": "merged",
                    "madr_link": "https://github.com/rust-lang/rfcs/pull/2394",
                    "proposed_on": "2018-04-06",
                },
            ]
        },
        neighbors={
            "rfc:2394": [
                ("AREA", "rfc:2394", "area:async", ("area:async", ["Area"], {"name": "async"})),
            ]
        },
    )


def _plan() -> AnswerPlan:
    node = EvidenceNode(
        id="rfc:2394",
        label="Decision",
        properties={"id": "rfc:2394", "title": "async/await notation",
                    "madr_link": "https://github.com/rust-lang/rfcs/pull/2394"},
        source="fulltext",
        score=1.0,
    )
    verdict = ClaimVerdict(
        sentence="Rust landed async/await in RFC 2394.",
        cited=True,
        confidence=0.9,
        evidence_ids=("rfc:2394",),
        escalated=False,
    )
    return AnswerPlan(
        route="decision-provenance",
        route_confidence=0.9,
        route_escalated=False,
        candidate_count=1,
        rounds=1,
        stopped_early=False,
        queries=("MATCH (d:Decision) RETURN d",),
        evidence_nodes=(node,),
        sentences=(verdict.sentence,),
        verdicts=(verdict,),
        citation_count=1,
        claims_total=1,
        claims_cited=1,
        abstention_required=False,
        abstention=None,
    )


def test_node_report_has_title_source_and_impact() -> None:
    markdown = exports.render_report(_reader(), node_id="rfc:2394")

    assert "# Decision rfc:2394: async/await notation" in markdown
    assert "https://github.com/rust-lang/rfcs/pull/2394" in markdown
    assert "- status: merged" in markdown
    assert "## Impact" in markdown
    assert "- nodes: 2" in markdown
    assert "- evidence types: AREA" in markdown


def test_unknown_node_report_raises_404() -> None:
    with pytest.raises(exports.ExportError) as error:
        exports.render_report(_reader(), node_id="rfc:999")

    assert error.value.status_code == 404


def test_unknown_scenario_raises_400() -> None:
    with pytest.raises(exports.ExportError) as error:
        exports.render_report(_reader(), scenario="nope")

    assert error.value.status_code == 400


def test_cold_scenario_raises_409() -> None:
    cache.clear()
    with pytest.raises(exports.ExportError) as error:
        exports.render_report(_reader(), scenario="ask_corpus")

    assert error.value.status_code == 409


def test_cached_scenario_renders_the_answer_with_citations() -> None:
    cache.clear()
    cache.put("async_story", _plan())
    try:
        markdown = exports.render_report(_reader(), scenario="async_story")
    finally:
        cache.clear()

    assert "# Scenario: async_story" in markdown
    assert "Which RFC introduced" in markdown
    assert "[cited] Rust landed async/await in RFC 2394." in markdown
    assert "Decision rfc:2394: async/await notation" in markdown


def test_missing_arguments_raise_400() -> None:
    with pytest.raises(exports.ExportError) as error:
        exports.render_report(_reader())

    assert error.value.status_code == 400


def test_render_graph_returns_the_impact_payload() -> None:
    payload = exports.render_graph(_reader(), "rfc:2394")

    assert payload["seed"] == "rfc:2394"
    assert {node["id"] for node in payload["nodes"]} == {"rfc:2394", "area:async"}


def test_render_graph_missing_node_raises_404() -> None:
    with pytest.raises(exports.ExportError) as error:
        exports.render_graph(_reader(), "rfc:999")

    assert error.value.status_code == 404


def test_export_filename_sanitizes_the_id() -> None:
    assert exports.export_filename(node_id="rfc:2394", suffix="md") == "rfc-2394.md"
    assert exports.export_filename(scenario="async_story", suffix="json") == "async_story.json"


def test_report_endpoint_downloads_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", _reader)

    with TestClient(app) as client:
        response = client.post("/exports/report", json={"node_id": "rfc:2394"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == 'attachment; filename="rfc-2394.md"'
    assert "# Decision rfc:2394" in response.text


def test_report_endpoint_returns_409_for_a_cold_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    monkeypatch.setattr(main, "connect_from_env", _reader)

    with TestClient(app) as client:
        response = client.post("/exports/report", json={"scenario": "ask_corpus"})

    assert response.status_code == 409


def test_report_endpoint_returns_404_for_an_unknown_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", _reader)

    with TestClient(app) as client:
        response = client.post("/exports/report", json={"node_id": "rfc:999"})

    assert response.status_code == 404


def test_graph_endpoint_downloads_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", _reader)

    with TestClient(app) as client:
        response = client.post("/exports/graph", json={"node_id": "rfc:2394"})

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="rfc-2394.json"'
    assert response.json()["seed"] == "rfc:2394"
