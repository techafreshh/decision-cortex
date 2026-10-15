"""Integration tests for the Phase-1 ingestion path against a real FalkorDB.

Marked ``integration``: run in CI by ``falkordb-integration.yml`` (a FalkorDB
service container with ``FALKORDB_HOST``/``FALKORDB_PORT`` set and
``OPENROUTER_API_KEY`` emptied) and skipped in offline runs. The SDK is
imported lazily so collection never needs it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from ingest import graph

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase1"
GRAPH_NAME = "dc_integration"

#: PRD.md §15.3 reference query, verbatim.
REFERENCE_QUERY = (
    'MATCH (d:Decision)-[e:ABOUT]->(c:Concept {name:"trait objects"}) '
    "MATCH (p:Person)-[o:OBJECTED]->(d) "
    "RETURN d.title, d.status, o.evidence, collect(p.handle);"
)

pytestmark = pytest.mark.integration


def _target() -> tuple[str, int]:
    host = os.environ.get("FALKORDB_HOST")
    port = os.environ.get("FALKORDB_PORT")
    if not host or not port:
        pytest.skip("FALKORDB_HOST/FALKORDB_PORT unset; integration needs a FalkorDB")
    return host, int(port)


def _connection(host: str, port: int):
    from graphrag_sdk import ConnectionConfig, FalkorDBConnection

    return FalkorDBConnection(
        ConnectionConfig(host=host, port=port, graph_name=GRAPH_NAME)
    )


async def _reset(host: str, port: int) -> None:
    from graphrag_sdk.storage.graph_store import GraphStore

    connection = _connection(host, port)
    store = GraphStore(connection)
    try:
        await store.delete_all()
    finally:
        await connection.close()


async def _query(host: str, port: int, cypher: str) -> list[list[object]]:
    connection = _connection(host, port)
    try:
        result = await connection.query(cypher)
        return [list(row) for row in result.result_set]
    finally:
        await connection.close()


async def _counts(host: str, port: int) -> dict[str, object]:
    connection = _connection(host, port)
    try:
        node_total = (await connection.query("MATCH (n) RETURN count(n)")).result_set[0][0]
        edge_total = (
            await connection.query("MATCH ()-[r]->() RETURN count(r)")
        ).result_set[0][0]
        labels = await connection.query(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) ORDER BY label"
        )
        types = await connection.query(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) ORDER BY type"
        )
    finally:
        await connection.close()
    return {
        "nodes": node_total,
        "edges": edge_total,
        "labels": {row[0]: row[1] for row in labels.result_set},
        "types": {row[0]: row[1] for row in types.result_set},
    }


def test_reference_query_returns_expected_rows() -> None:
    host, port = _target()
    asyncio.run(_reset(host, port))
    asyncio.run(
        graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME)
    )

    rows = asyncio.run(_query(host, port, REFERENCE_QUERY))

    assert rows == [
        [
            "Trait objects",
            "accepted",
            "https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001",
            ["bob"],
        ]
    ]


def test_reingest_is_count_idempotent() -> None:
    host, port = _target()
    asyncio.run(_reset(host, port))
    asyncio.run(
        graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME)
    )
    first = asyncio.run(_counts(host, port))

    asyncio.run(
        graph.ingest_snapshot(FIXTURE, host=host, port=port, graph_name=GRAPH_NAME)
    )
    second = asyncio.run(_counts(host, port))

    assert first["nodes"] == 14
    assert first["edges"] == 16
    assert first == second
