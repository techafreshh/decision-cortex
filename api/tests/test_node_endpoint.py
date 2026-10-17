"""Offline tests for node detail and the ``GET /node/{id}`` endpoint.

A fake :class:`GraphReader` returns canned rows for the indexed ``__Entity__``
lookup, so no graph and no network are involved.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import main, nodes
from api.main import app


class NodeReader:
    """Returns one canned row for any query; records the calls it saw."""

    def __init__(self, row: list[Any] | None) -> None:
        self.row = row
        self.calls: list[tuple[str, Any]] = []

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        self.calls.append((cypher, params))
        return [] if self.row is None else [self.row]


def test_unlabelled_node_yields_an_empty_label() -> None:
    # The query filters ``__Entity__`` out, so a node the schema does not label
    # comes back with no labels and must not be given a prefix-derived one.
    reader = NodeReader([[], {"id": "mystery:1"}])

    detail = nodes.node_detail(reader, "mystery:1")

    assert detail is not None
    assert detail["label"] == ""


def test_message_detail_carries_the_source_block() -> None:
    reader = NodeReader(
        [
            ["Message", "__Entity__"],
            {
                "id": "message:5001",
                "pr_id": 200,
                "comment_id": 5001,
                "author": "bob",
                "ts": "2019-01-01T00:00:00Z",
                "text_ref": "https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001",
                "stance_hint": None,
                "truncated": True,
            },
        ]
    )

    detail = nodes.node_detail(reader, "message:5001")

    assert detail is not None
    assert detail["id"] == "message:5001"
    assert detail["label"] == "Message"
    assert detail["properties"]["truncated"] is True
    assert detail["source"] == {
        "url": "https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001",
        "author": "bob",
        "date": "2019-01-01T00:00:00Z",
        "stance": None,
        "truncated": True,
    }
    assert reader.calls[0][1] == {"id": "message:5001"}


def test_decision_source_falls_back_to_proposed_on() -> None:
    reader = NodeReader(
        [
            ["Decision", "__Entity__"],
            {"id": "rfc:200", "title": "Trait objects", "madr_link": "https://rfc/200",
             "decided_on": None, "proposed_on": "2014-06-01"},
        ]
    )

    detail = nodes.node_detail(reader, "rfc:200")

    assert detail is not None
    assert detail["label"] == "Decision"
    assert detail["source"]["url"] == "https://rfc/200"
    assert detail["source"]["date"] == "2014-06-01"


def test_commit_source_has_no_url() -> None:
    reader = NodeReader(
        [["Commit", "__Entity__"], {"id": "commit:abc", "ts": "2015-02-02", "message": "Add RFC"}]
    )

    detail = nodes.node_detail(reader, "commit:abc")

    assert detail is not None
    assert detail["label"] == "Commit"
    assert detail["source"]["url"] is None
    assert detail["source"]["date"] == "2015-02-02"


def test_docversion_source_uses_content_ref() -> None:
    reader = NodeReader(
        [
            ["DocVersion", "__Entity__"],
            {"id": "docversion:200", "content_ref": "https://rfc/200.md", "ts": "2014-06-01"},
        ]
    )

    detail = nodes.node_detail(reader, "docversion:200")

    assert detail is not None
    assert detail["source"]["url"] == "https://rfc/200.md"
    assert detail["source"]["date"] == "2014-06-01"


def test_embedding_property_is_omitted() -> None:
    reader = NodeReader(
        [["Decision", "__Entity__"], {"id": "rfc:200", "embedding": [0.1, 0.2]}]
    )

    detail = nodes.node_detail(reader, "rfc:200")

    assert detail is not None
    assert "embedding" not in detail["properties"]


def test_missing_node_returns_none() -> None:
    assert nodes.node_detail(NodeReader(None), "rfc:999") is None


def test_endpoint_returns_404_for_an_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "connect_from_env", lambda: NodeReader(None))

    with TestClient(app) as client:
        response = client.get("/node/rfc:999")

    assert response.status_code == 404
    assert "rfc:999" in response.json()["detail"]


def test_endpoint_returns_the_node_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = NodeReader(
        [
            ["Message", "__Entity__"],
            {"id": "message:5001", "author": "bob", "text_ref": "https://c/5001"},
        ]
    )
    monkeypatch.setattr(main, "connect_from_env", lambda: reader)

    with TestClient(app) as client:
        response = client.get("/node/message:5001")

    assert response.status_code == 200
    assert response.json()["source"]["url"] == "https://c/5001"
