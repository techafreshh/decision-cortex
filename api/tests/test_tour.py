"""Offline tests for the curated lifecycle tours (``api/tours.py``).

The async/await spine must be the *real* corpus history, so the first test
pins every RFC number, status, and order to ``snapshot/rfcs.jsonl``. The rest
exercise ``build_tour`` with a fake reader: graph-resolved fields, dropped
absent stages, and the lifecycle-labelled transitions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api import tours

_RFCS_JSONL = Path(__file__).resolve().parents[2] / "snapshot" / "rfcs.jsonl"


def _snapshot_rfcs() -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    with _RFCS_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            records[record["rfc"]] = record
    return records


class TourReader:
    def __init__(self, known: dict[int, dict[str, Any]]) -> None:
        self.known = known

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        assert cypher == tours._TOUR_NODE_QUERY
        node_id = params["id"]
        rfc = int(node_id.split(":")[1])
        if rfc not in self.known:
            return []
        record = self.known[rfc]
        node = {
            "id": node_id,
            "label": "Decision",
            "properties": {
                "id": node_id,
                "rfc": rfc,
                "title": record["title"],
                "status": record["status"],
                "proposed_on": record["proposed_on"],
                "decided_on": record["decided_on"],
            },
        }
        return [[node]]


def test_spine_matches_the_snapshot() -> None:
    snapshot = _snapshot_rfcs()
    expected_status = {
        53: "rejected",
        1083: "rejected",
        1823: "rejected",
        2033: "merged",
        2394: "merged",
        2592: "merged",
        2932: "merged",
        3083: "rejected",
        3185: "merged",
        3668: "merged",
    }

    assert [stage.rfc for stage in tours.ASYNC_AWAIT_TOUR] == list(expected_status)
    for stage in tours.ASYNC_AWAIT_TOUR:
        assert stage.rfc in snapshot
        assert snapshot[stage.rfc]["status"] == expected_status[stage.rfc]
        assert stage.role
        assert stage.narrative


def test_spine_is_chronological() -> None:
    snapshot = _snapshot_rfcs()
    proposed = [snapshot[stage.rfc]["proposed_on"] for stage in tours.ASYNC_AWAIT_TOUR]

    assert proposed == sorted(proposed)


def test_build_tour_resolves_fields_and_labels_transitions() -> None:
    snapshot = _snapshot_rfcs()
    reader = TourReader(snapshot)

    result = tours.build_tour(reader, "async_await")

    assert result is not None
    assert result["tour"] == "async_await"
    assert len(result["stages"]) == len(tours.ASYNC_AWAIT_TOUR)
    first = result["stages"][0]
    assert first["id"] == "rfc:53"
    assert first["title"] == snapshot[53]["title"]
    assert first["status"] == "rejected"
    assert first["role"] == "first-attempt"
    assert first["narrative"] == tours.ASYNC_AWAIT_TOUR[0].narrative
    assert len(result["transitions"]) == len(result["stages"]) - 1
    assert result["transitions"][0] == {
        "from": "rfc:53",
        "to": "rfc:1083",
        "label": tours.ASYNC_AWAIT_TOUR[1].role,
    }


def test_build_tour_drops_stages_absent_from_the_graph() -> None:
    snapshot = {rfc: record for rfc, record in _snapshot_rfcs().items() if rfc != 1823}

    result = tours.build_tour(TourReader(snapshot), "async_await")

    assert result is not None
    assert "rfc:1823" not in [stage["id"] for stage in result["stages"]]
    assert len(result["stages"]) == len(tours.ASYNC_AWAIT_TOUR) - 1


def test_unknown_tour_returns_none() -> None:
    assert tours.build_tour(TourReader({}), "does_not_exist") is None
