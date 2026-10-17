"""Offline tests for the decision timeline (``api/timeline.py``).

A fake :class:`GraphReader` returns canned rows per query shape, so the
chronological ordering, area/team attachment and filtering, supersession chain,
and stance ranking are all exercised with no graph and no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import main, timeline
from api.main import app


def decision(node_id: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "label": "Decision", "properties": {"id": node_id, **properties}}


class TimelineReader:
    def __init__(
        self,
        *,
        decisions: list[dict[str, Any]],
        areas: list[list[Any]] | None = None,
        teams: list[list[Any]] | None = None,
        supersedes: list[list[Any]] | None = None,
        stances: list[list[Any]] | None = None,
    ) -> None:
        self.decisions = decisions
        self.areas = areas or []
        self.teams = teams or []
        self.supersedes = supersedes or []
        self.stances = stances or []

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        if cypher == timeline._DECISIONS_QUERY:
            return [[item] for item in self.decisions]
        if "[:AREA]->(a:Area)" in cypher:
            return self.areas
        if "[:ASSOCIATED_TEAM]->(t:Team)" in cypher:
            return self.teams
        if "[:SUPERSEDES]->(e:Decision)" in cypher:
            return self.supersedes
        if "OBJECTED|SUPPORTED|MODERATED" in cypher:
            return self.stances
        raise AssertionError(f"unexpected cypher: {cypher}")


def test_decisions_are_chronological_with_relations_attached() -> None:
    reader = TimelineReader(
        decisions=[
            decision("rfc:2", rfc=2, title="Second", status="merged",
                     proposed_on="2018-01-01", decided_on="2018-02-01"),
            decision("rfc:1", rfc=1, title="First", status="rejected",
                     proposed_on="2014-01-01", decided_on="2014-02-01"),
        ],
        areas=[["rfc:2", "async"], ["rfc:1", "privacy"]],
        teams=[["rfc:2", "lang"]],
        supersedes=[["rfc:2", "rfc:1"]],
        stances=[
            ["rfc:1", "carol", "OBJECTED", {"evidence": "c", "confidence": 0.4}],
            ["rfc:1", "bob", "SUPPORTED", {"evidence": "b", "confidence": 0.9}],
        ],
    )

    result = timeline.build_timeline(reader)

    assert [item["id"] for item in result["decisions"]] == ["rfc:1", "rfc:2"]
    first = result["decisions"][0]
    assert first["areas"] == ["privacy"]
    assert first["teams"] == []
    assert first["superseded_by"] == [2]
    assert [stance["handle"] for stance in first["stances"]] == ["bob", "carol"]
    # Each stance carries its provenance (`{evidence, confidence}`) for jump-to-source.
    assert first["stances"] == [
        {"handle": "bob", "kind": "SUPPORTED", "evidence": "b", "confidence": 0.9},
        {"handle": "carol", "kind": "OBJECTED", "evidence": "c", "confidence": 0.4},
    ]
    assert result["supersede_edges"] == [{"src": "rfc:2", "dst": "rfc:1"}]
    assert result["decisions"][1]["supersedes"] == [1]
    assert result["areas"] == ["async", "privacy"]
    assert result["teams"] == ["lang"]


def test_area_and_team_filters_narrow_the_set() -> None:
    reader = TimelineReader(
        decisions=[
            decision("rfc:1", rfc=1, title="A", proposed_on="2014-01-01"),
            decision("rfc:2", rfc=2, title="B", proposed_on="2015-01-01"),
        ],
        areas=[["rfc:1", "async"], ["rfc:2", "privacy"]],
        teams=[["rfc:2", "lang"]],
    )

    by_area = timeline.build_timeline(reader, area="async")
    assert [item["id"] for item in by_area["decisions"]] == ["rfc:1"]
    assert by_area["supersede_edges"] == []

    by_team = timeline.build_timeline(reader, team="lang")
    assert [item["id"] for item in by_team["decisions"]] == ["rfc:2"]


def test_undated_decisions_sort_last() -> None:
    reader = TimelineReader(
        decisions=[
            decision("rfc:9", rfc=9, title="Undated"),
            decision("rfc:1", rfc=1, title="Dated", proposed_on="2014-01-01"),
        ]
    )

    result = timeline.build_timeline(reader)

    assert [item["id"] for item in result["decisions"]] == ["rfc:1", "rfc:9"]


def test_registered_tours_are_advertised() -> None:
    reader = TimelineReader(decisions=[])

    assert timeline.build_timeline(reader)["tours"] == ["async_await"]


class TourReader(TimelineReader):
    """Also answers the ``rfc:<n>`` Decision lookup the tour resolver issues."""

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        if "MATCH (d:Decision {id: $id})" in cypher:
            rfc = int(params["id"].split(":")[1])
            if rfc != 2394:
                return []
            return [[decision("rfc:2394", rfc=2394, title="async/await", status="merged",
                              proposed_on="2018-04-06", decided_on="2018-05-08")]]
        return super().query(cypher, params)


def test_timeline_endpoint_returns_the_flat_timeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", lambda: TimelineReader(decisions=[]))

    with TestClient(app) as client:
        response = client.get("/timeline")

    assert response.status_code == 200
    assert response.json()["tours"] == ["async_await"]


def test_timeline_endpoint_serves_a_tour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", lambda: TourReader(decisions=[]))

    with TestClient(app) as client:
        response = client.get("/timeline", params={"tour": "async_await"})

    assert response.status_code == 200
    assert response.json()["tour"] == "async_await"
    assert response.json()["stages"][0]["id"] == "rfc:2394"


def test_timeline_endpoint_rejects_an_unknown_tour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", lambda: TimelineReader(decisions=[]))

    with TestClient(app) as client:
        response = client.get("/timeline", params={"tour": "nope"})

    assert response.status_code == 400
