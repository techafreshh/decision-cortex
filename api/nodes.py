"""Node detail for the web ``SourcePanel`` (``GET /node/{id}``, PRD §10).

A citation chip carries only ``{id, label, title}`` (``api.answer._chip``), so
opening the real source means resolving the id against the graph. ``node_detail``
reads the node behind an ``__Entity__`` id index and returns its schema label,
its stored properties, and a derived ``source`` block.

The graph stores refs, never bodies: a ``Message`` carries ``text_ref`` (the
GitHub comment permalink), a ``DocVersion`` ``content_ref``, a ``Decision``
``madr_link``. The ``source`` block surfaces those as a canonical ``url`` plus
author/date/stance/truncated where the schema declares them, so the panel can
deep-link out to the real source instead of fabricating content the graph does
not hold. The ``embedding`` property is a derived vector-index artifact
(``docs/graph-schema-notes.md`` "Retrieval indexes are derived, out-of-band
data"), not a canonical property, so it is omitted from the response.

The label is the schema label namespaced by the id prefix
(``docs/graph-schema-notes.md`` "Id namespacing"); ``test_node_prefixes_match_
the_schema`` pins :data:`_LABEL_BY_PREFIX` to ``ontology.SCHEMA``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from api.retrieval import GraphReader

#: Id prefix -> schema label. Every node id is namespaced by its label
#: (``docs/graph-schema-notes.md``); the prefix map is the canonical decoding.
_LABEL_BY_PREFIX: dict[str, str] = {
    "rfc": "Decision",
    "person": "Person",
    "message": "Message",
    "commit": "Commit",
    "docversion": "DocVersion",
    "team": "Team",
    "area": "Area",
    "concept": "Concept",
    "issue": "Issue",
}

_SCHEMA_LABELS = frozenset(_LABEL_BY_PREFIX.values())

_NODE_QUERY = (
    "MATCH (n:__Entity__ {id: $id}) "
    "RETURN [l IN labels(n) WHERE l <> '__Entity__'] AS labels, properties(n) AS props"
)

#: The stable keys of the derived ``source`` block; ``null`` when a label's
#: schema declares no such property (e.g. a ``Commit`` has no url).
_SOURCE_KEYS = ("url", "author", "date", "stance", "truncated")


def label_from_id(node_id: str) -> str:
    """The schema label namespaced by ``node_id``'s prefix, or ``""`` if unknown."""
    return _LABEL_BY_PREFIX.get(node_id.split(":", 1)[0], "")


def node_detail(reader: GraphReader, node_id: str) -> dict[str, Any] | None:
    """Resolve ``node_id`` to ``{id, label, properties, source}``; ``None`` if absent."""
    rows = reader.query(_NODE_QUERY, {"id": node_id})
    if not rows:
        return None
    labels, raw_properties = rows[0][0], rows[0][1]
    properties = dict(raw_properties) if isinstance(raw_properties, Mapping) else {}
    properties.pop("embedding", None)
    label = _resolve_label(node_id, labels)
    return {
        "id": node_id,
        "label": label,
        "properties": properties,
        "source": source_block(label, properties),
    }


def source_block(label: str, properties: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the ``{url, author, date, stance, truncated}`` block for ``label``.

    Every key is always present; a label whose schema declares no such property
    (or a node missing the value) yields ``null`` so the panel renders an honest
    empty state rather than a missing field.
    """
    block: dict[str, Any] = dict.fromkeys(_SOURCE_KEYS)
    if label == "Message":
        block["url"] = properties.get("text_ref")
        block["author"] = properties.get("author")
        block["date"] = properties.get("ts")
        block["stance"] = properties.get("stance_hint")
        block["truncated"] = properties.get("truncated")
    elif label == "DocVersion":
        block["url"] = properties.get("content_ref")
        block["date"] = properties.get("ts")
    elif label == "Decision":
        block["url"] = properties.get("madr_link")
        block["date"] = properties.get("decided_on") or properties.get("proposed_on")
    elif label in ("Commit", "Issue"):
        block["date"] = properties.get("ts")
    return block


def _resolve_label(node_id: str, labels: Sequence[Any]) -> str:
    """Prefer the node's declared schema label, falling back to its id prefix."""
    for name in labels:
        if name in _SCHEMA_LABELS:
            return str(name)
    return label_from_id(node_id)
