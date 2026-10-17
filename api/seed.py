"""Seed-on-boot: replay the committed snapshot into an empty FalkorDB.

This is the one-shot step the ``api`` container runs before uvicorn starts
(``python -m api.seed && exec uvicorn ...``). It owns the deployment's
seed-on-boot promise without putting a 28k-node write inside FastAPI's startup:
the app stays side-effect-free and the unit suite never triggers an ingest.

The guard is a live count of the loader's two phases. An already-seeded graph is
left untouched — the loader is offline and LLM-free, so a replay costs no network
and no tokens, but skipping it keeps a restart cheap and makes the guard's effect
observable in the container logs. The loader (``ingest.graph``) is imported
lazily inside :func:`_load_snapshot` so importing ``api.seed`` (and therefore
``api.main``, which calls :func:`graph_is_seeded` from ``/healthz``) never
imports the ingestion stack.
"""

from __future__ import annotations

import asyncio
import os

from api.retrieval import (
    FalkorDBConnection,
    GraphReader,
    connect_from_env,
    connection_from_env,
)

#: ``ingest.graph.load_payload`` commits ``Decision`` nodes before their edges,
#: so the node count alone cannot tell a completed load from one interrupted
#: between the two writes.
_DECISION_COUNT_QUERY = "MATCH (d:Decision) RETURN count(d)"
#: Edges are the loader's terminal write; a graph with Decisions but no edges is
#: a partial load and must re-run, not read as seeded.
_EDGE_COUNT_QUERY = "MATCH ()-[r]->() RETURN count(r)"

#: The snapshot directory inside the ``api`` image, overridable for tests.
DEFAULT_SNAPSHOT_DIR = "snapshot"


def _count(reader: GraphReader, cypher: str) -> int:
    rows = reader.query(cypher)
    return int(rows[0][0]) if rows else 0


def graph_is_seeded(reader: GraphReader) -> bool:
    """Whether ``reader`` sees a *completed* seed (Decisions and their edges).

    A partial load — the loader commits nodes before relationships, so a boot
    killed mid-write can leave ``Decision`` nodes with no edges — reads as "not
    seeded", so the next boot re-runs the idempotent loader instead of skipping
    it. A down or unreachable database is "not seeded", never a crash:
    ``/healthz`` must answer honestly with no database reachable.
    """
    try:
        if _count(reader, _DECISION_COUNT_QUERY) == 0:
            return False
        return _count(reader, _EDGE_COUNT_QUERY) > 0
    except Exception:  # noqa: BLE001 — any read failure is "not seeded", not a crash
        return False


def seed_if_empty(
    *,
    reader: GraphReader,
    snapshot_dir: str,
    host: str,
    port: int,
    graph_name: str,
) -> bool:
    """Load the snapshot into an empty graph; return whether it loaded.

    A graph that already passes :func:`graph_is_seeded` is left unchanged
    (``False``) without loading.
    """
    if graph_is_seeded(reader):
        return False
    _load_snapshot(
        snapshot_dir=snapshot_dir, host=host, port=port, graph_name=graph_name
    )
    return True


def _load_snapshot(
    *, snapshot_dir: str, host: str, port: int, graph_name: str
) -> None:
    """Run the idempotent snapshot loader; the only ``ingest`` import."""
    from ingest.graph import ingest_snapshot

    asyncio.run(
        ingest_snapshot(snapshot_dir, host=host, port=port, graph_name=graph_name)
    )


def main() -> int:
    """Entrypoint for ``python -m api.seed``; prints the guard's outcome."""
    connection: FalkorDBConnection = connection_from_env()
    snapshot_dir = os.environ.get("SNAPSHOT_DIR", "").strip() or DEFAULT_SNAPSHOT_DIR
    seeded = seed_if_empty(
        reader=connect_from_env(),
        snapshot_dir=snapshot_dir,
        host=connection.host,
        port=connection.port,
        graph_name=connection.graph_name,
    )
    print(
        "seed-on-boot: seeded snapshot"
        if seeded
        else "seed-on-boot: graph already seeded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
