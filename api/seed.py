"""Seed-on-boot: replay the committed snapshot into an empty FalkorDB.

This is the one-shot step the ``api`` container runs before uvicorn starts
(``python -m api.seed && exec uvicorn ...``). It owns the deployment's
seed-on-boot promise without putting a 28k-node write inside FastAPI's startup:
the app stays side-effect-free and the unit suite never triggers an ingest.

The guard is a live ``Decision`` count. An already-seeded graph is left
untouched — the loader is offline and LLM-free, so a replay costs no network
and no tokens, but skipping it keeps a restart cheap and makes the guard's
effect observable in the container logs. The loader (``ingest.graph``) is
imported lazily inside :func:`_load_snapshot` so importing ``api.seed`` (and
therefore ``api.main``, which calls :func:`graph_is_seeded` from ``/healthz``)
never imports the ingestion stack.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from api.retrieval import (
    FalkorDBConnection,
    GraphReader,
    connect_from_env,
    connection_from_env,
)

#: The graph is seeded when at least one ``Decision`` exists.
_DECISION_COUNT_QUERY = "MATCH (d:Decision) RETURN count(d)"

#: The snapshot directory inside the ``api`` image, overridable for tests.
DEFAULT_SNAPSHOT_DIR = "snapshot"


def graph_is_seeded(reader: GraphReader) -> bool:
    """Whether ``reader`` sees a seeded graph (any ``Decision`` present).

    A down or unreachable database is "not seeded", never a crash: ``/healthz``
    must answer honestly with no database reachable.
    """
    try:
        rows = reader.query(_DECISION_COUNT_QUERY)
        return bool(rows) and int(rows[0][0]) > 0
    except Exception:  # noqa: BLE001 — any read failure is "not seeded", not a crash
        return False


def seed_if_empty(
    *,
    reader: GraphReader,
    snapshot_dir: str,
    host: str,
    port: int,
    graph_name: str,
    load: Callable[..., Any] | None = None,
) -> bool:
    """Load the snapshot into an empty graph; return whether it loaded.

    A non-empty graph is returned unchanged (``False``) without calling
    ``load``. ``load`` is the injection seam tests use; the default is
    :func:`_load_snapshot`.
    """
    if graph_is_seeded(reader):
        return False
    active_load = load or _load_snapshot
    active_load(snapshot_dir=snapshot_dir, host=host, port=port, graph_name=graph_name)
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
