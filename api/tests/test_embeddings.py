"""Offline unit tests for the OpenRouter embeddings helper.

Every test substitutes the ``_post_embeddings`` seam, so no HTTP call and no
API key are ever needed (``OPENROUTER_API_KEY`` is pinned empty).
"""

from __future__ import annotations

import pytest

from api import llm

ENV_VARS = (
    "OPENROUTER_API_KEY",
    "EMBEDDING_MODEL_SLUG",
    "EMBEDDING_DIMENSION",
    "SPEND_CAP_USD",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "")
    with llm._ledger_lock:
        llm._ledger.clear()


class FakeEmbeddings:
    """Replaces the HTTP seam with canned vectors and records payloads."""

    def __init__(self, vectors: list[list[float]], cost: float | None = None) -> None:
        self.vectors = vectors
        self.cost = cost
        self.payloads: list[dict[str, object]] = []

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        data = {
            "data": [
                {"embedding": vector, "index": index, "object": "embedding"}
                for index, vector in enumerate(self.vectors)
            ],
            "object": "list",
        }
        if self.cost is not None:
            data["usage"] = {"cost": self.cost}
        return data


def test_embed_query_returns_vector_with_cost_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL_SLUG", "test/embedder")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "3")
    fake = FakeEmbeddings([[0.1, 0.2, 0.3]], cost=0.0002)
    monkeypatch.setattr(llm, "_post_embeddings", fake)

    result = llm.embed_query("who objected?")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.cost_usd == 0.0002
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0
    assert fake.payloads[0]["model"] == "test/embedder"
    assert fake.payloads[0]["input"] == ["who objected?"]
    assert fake.payloads[0]["dimensions"] == 3
    assert llm.ledger_records() == []


def test_embed_documents_returns_vectors_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_DIMENSION", "2")
    fake = FakeEmbeddings([[1.0, 1.1], [2.0, 2.1]])
    monkeypatch.setattr(llm, "_post_embeddings", fake)

    vectors = llm.embed_documents(["first", "second"])

    assert vectors == [[1.0, 1.1], [2.0, 2.1]]
    assert fake.payloads[0]["input"] == ["first", "second"]
    assert fake.payloads[0]["model"] == llm.DEFAULT_EMBEDDING_MODEL_SLUG


def test_embed_query_rejects_a_wrong_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIMENSION", "4")
    monkeypatch.setattr(llm, "_post_embeddings", FakeEmbeddings([[0.1, 0.2, 0.3]]))

    with pytest.raises(llm.EmbeddingError, match="expected 4"):
        llm.embed_query("short vector")


def test_embed_documents_rejects_a_vector_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_DIMENSION", "2")
    monkeypatch.setattr(llm, "_post_embeddings", FakeEmbeddings([[1.0, 2.0]]))

    with pytest.raises(llm.EmbeddingError, match="2 inputs"):
        llm.embed_documents(["one", "two"])


def test_embed_query_requires_an_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm.embed_query("no key")


class _FakeResponse:
    def __init__(self, data: object) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._data


def test_post_embeddings_targets_openrouter_with_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    sent: list[dict[str, object]] = []

    def fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> _FakeResponse:
        sent.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse({"data": []})

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    data = llm._post_embeddings({"model": "m", "input": ["x"]})

    assert data == {"data": []}
    assert sent[0]["url"] == llm.OPENROUTER_EMBEDDINGS_URL
    assert sent[0]["headers"] == {
        "Authorization": "Bearer sk-test-123",
        "Content-Type": "application/json",
    }
    assert sent[0]["timeout"] == llm._REQUEST_TIMEOUT_S


def test_post_embeddings_rejects_a_non_object_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _FakeResponse(["nope"]))

    with pytest.raises(llm.EmbeddingError):
        llm._post_embeddings({"model": "m", "input": ["x"]})
