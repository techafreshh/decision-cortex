"""Shared test doubles for the answer-pipeline tests.

No network and no graph: a fake reader returns canned Cypher rows, and
:class:`DispatchOpenRouter` answers ``_post_chat_completion`` by inspecting the
request's JSON schema (router vs. sufficiency vs. claim gate vs. reason).
"""

from __future__ import annotations

import json
from typing import Any

from api import llm, retrieval


def node(label: str, node_id: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "label": label, "properties": {"id": node_id, **properties}}


def evidence_node(label: str, node_id: str, **properties: Any) -> retrieval.EvidenceNode:
    return retrieval.EvidenceNode(
        id=node_id,
        label=label,
        properties={"id": node_id, **properties},
        source="fulltext",
        score=1.0,
    )


class FakeReader:
    """Dispatches on the query shape; each field is canned rows."""

    def __init__(
        self,
        *,
        vector: list[tuple[str, float]] | None = None,
        fulltext: list[tuple[str, float]] | None = None,
        out: dict[str, list[tuple[str, dict[str, Any]]]] | None = None,
        incoming: dict[str, list[tuple[str, dict[str, Any]]]] | None = None,
    ) -> None:
        self.vector = vector or []
        self.fulltext = fulltext or []
        self.out = out or {}
        self.incoming = incoming or {}
        self.calls: list[tuple[str, Any]] = []

    def query(self, cypher: str, params: Any = None) -> list[list[Any]]:
        self.calls.append((cypher, params))
        if "vector.queryNodes" in cypher:
            return [[node("Decision", nid), score] for nid, score in self.vector]
        if "fulltext.queryNodes" in cypher:
            return [[node("Decision", nid), score] for nid, score in self.fulltext]
        if "MATCH (d:Decision)-[r]->(n)" in cypher:
            rows: list[list[Any]] = []
            for did in params["ids"]:
                rows.extend([did, rel, val] for rel, val in self.out.get(did, []))
            return rows
        if "MATCH (n)-[r]->(d:Decision)" in cypher:
            rows = []
            for did in params["ids"]:
                rows.extend([val, rel, did] for rel, val in self.incoming.get(did, []))
            return rows
        raise AssertionError(f"unexpected cypher: {cypher}")


def provenance_reader() -> FakeReader:
    """A reader that seeds ``rfc:200`` and walks to a comment and a person.

    Node properties mirror the declared schema: a ``Message`` carries a
    ``text_ref`` permalink and a ``Person`` its ``handle`` — never a ``title``
    the parser does not emit.
    """
    return FakeReader(
        fulltext=[("rfc:200", 3.0)],
        out={
            "rfc:200": [
                (
                    "EVIDENCED_BY",
                    node(
                        "Message",
                        "message:5001",
                        text_ref="https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001",
                    ),
                ),
                ("PROPOSED_BY", node("Person", "person:bob", handle="bob")),
            ]
        },
    )


class PipelineDecide:
    """A ``decide`` seam that answers the router, sufficiency, and gate calls."""

    def __init__(
        self,
        *,
        route: str = "decision-provenance",
        gate: str = "e0",
        gate_choices: list[str] | None = None,
        sufficient: bool = True,
    ) -> None:
        self.route = route
        self.gate = gate
        #: When set, consumed one entry per claim-gate call (one per sentence),
        #: so a test can cite some sentences and reject others. The last entry
        #: repeats if more sentences arrive than choices.
        self.gate_choices = list(gate_choices) if gate_choices is not None else None
        self._gate_index = 0
        self.sufficient = sufficient

    def __call__(self, prompt: str, *, one_of=None, rating=None, yes_no=None, criteria=None):
        if yes_no is not None:
            return llm.DecideResult(
                choice=self.sufficient, confidence=0.9, escalated=False
            )
        assert one_of is not None
        if "out-of-graph" in one_of:
            return llm.DecideResult(choice=self.route, confidence=0.9, escalated=False)
        return llm.DecideResult(choice=self._next_gate(), confidence=0.9, escalated=False)

    def _next_gate(self) -> str:
        if self.gate_choices is None:
            return self.gate
        index = min(self._gate_index, len(self.gate_choices) - 1)
        self._gate_index += 1
        return self.gate_choices[index]


def completion(content: str, cost: float | None = None) -> dict[str, object]:
    data: dict[str, object] = {"choices": [{"message": {"content": content}}]}
    if cost is not None:
        data["usage"] = {"cost": cost}
    return data


def decision(choice: object, confidence: float) -> str:
    return json.dumps({"choice": choice, "confidence": confidence})


class DispatchOpenRouter:
    """A ``_post_chat_completion`` stub that answers by request schema."""

    def __init__(
        self,
        *,
        reason_text: str,
        gate_choice: str = "e0",
        gate_choices: list[str] | None = None,
        route: str = "decision-provenance",
        sufficient: bool = True,
        reason_cost: float = 0.0,
    ) -> None:
        self.reason_text = reason_text
        self.gate_choice = gate_choice
        #: When set, consumed one entry per claim-gate call (one per sentence),
        #: so a test can cite some sentences and reject others. The last entry
        #: repeats if more sentences arrive than choices.
        self.gate_choices = list(gate_choices) if gate_choices is not None else None
        self._gate_index = 0
        self.route = route
        self.sufficient = sufficient
        self.reason_cost = reason_cost
        self.payloads: list[dict[str, object]] = []
        self.reason_calls = 0

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        response_format = payload.get("response_format")
        if response_format is None:
            self.reason_calls += 1
            return completion(self.reason_text, cost=self.reason_cost)
        json_schema = response_format["json_schema"]  # type: ignore[index]
        schema = json_schema["schema"]
        choice = schema["properties"]["choice"]
        if choice.get("type") == "boolean":
            return completion(decision(self.sufficient, 0.9))
        if "out-of-graph" in choice.get("enum", []):
            return completion(decision(self.route, 0.9))
        return completion(decision(self._next_gate_choice(), 0.9))

    def _next_gate_choice(self) -> str:
        if self.gate_choices is None:
            return self.gate_choice
        index = min(self._gate_index, len(self.gate_choices) - 1)
        self._gate_index += 1
        return self.gate_choices[index]
