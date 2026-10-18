"""Integration test for the impact walk against a real FalkorDB.

Marked ``integration``: run in CI by ``falkordb-integration.yml`` (a FalkorDB
service container with ``FALKORDB_HOST``/``FALKORDB_PORT`` set and
``OPENROUTER_API_KEY`` emptied) and skipped in offline runs. The phase-1
fixture carries ``concepts.jsonl`` / ``stances.jsonl``, so this is the only
place the ``Concept``/``ABOUT`` and stance edges are traversed for real.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main, retrieval, tours
from api.main import app
from ingest import graph

FIXTURE = Path(__file__).resolve().parents[2] / "ingest" / "tests" / "fixtures" / "phase1"
GRAPH_NAME = "dc_impact_integration"

pytestmark = pytest.mark.integration


def _target() -> tuple[str, int]:
    host = os.environ.get("FALKORDB_HOST")
    port = os.environ.get("FALKORDB_PORT")
    if not host or not port:
        pytest.skip("FALKORDB_HOST/FALKORDB_PORT unset; integration needs a FalkorDB")
    return host, int(port)


def _reset(host: str, port: int) -> None:
    from falkordb import FalkorDB

    FalkorDB(host=host, port=port).select_graph(GRAPH_NAME).query(
        "MATCH (n) DETACH DELETE n"
    )


def _seed(monkeypatch: pytest.MonkeyPatch) -> tuple[str, int]:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    host, port = _target()
    _reset(host, port)
    asyncio.run(graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME))
    return host, port


def _client(monkeypatch: pytest.MonkeyPatch, host: str, port: int) -> TestClient:
    """Bind the app's reader to the freshly seeded fixture graph."""
    monkeypatch.setattr(
        main,
        "connect_from_env",
        lambda: retrieval.FalkorDBGraphReader(host=host, port=port, graph_name=GRAPH_NAME),
    )
    return TestClient(app)


def test_impact_endpoint_returns_the_blast_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    host, port = _seed(monkeypatch)

    with _client(monkeypatch, host, port) as client:
        response = client.get("/graph/impact/rfc:200")

    assert response.status_code == 200
    payload = response.json()
    assert payload["seed"] == "rfc:200"
    assert len(payload["nodes"]) >= 1
    node_ids = {node["id"] for node in payload["nodes"]}
    assert "concept:trait-objects" in node_ids
    assert "rfc:300" in node_ids
    assert "person:bob" in node_ids
    assert {"ABOUT", "SUPERSEDES", "OBJECTED"} <= set(payload["evidence_types"])
    assert payload["truncated"] is False


def test_impact_endpoint_reports_an_absent_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    host, port = _seed(monkeypatch)

    with _client(monkeypatch, host, port) as client:
        response = client.get("/graph/impact/rfc:99999")

    assert response.status_code == 404


def test_timeline_endpoint_reads_the_fixture_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, port = _seed(monkeypatch)

    with _client(monkeypatch, host, port) as client:
        response = client.get("/timeline")

    assert response.status_code == 200
    payload = response.json()
    by_id = {decision["id"]: decision for decision in payload["decisions"]}
    assert {"rfc:100", "rfc:200", "rfc:300"} <= set(by_id)
    assert by_id["rfc:200"]["superseded_by"] == [300]
    assert by_id["rfc:300"]["supersedes"] == [200]
    assert by_id["rfc:200"]["stances"][0]["handle"] == "bob"
    assert by_id["rfc:200"]["stances"][0]["kind"] == "OBJECTED"
    assert payload["tours"] == sorted(tours.TOURS)
