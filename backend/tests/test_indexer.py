from test_foundation import system, add
from clueshelf.embeddings import EmbeddingUnavailable, MODEL_NAME
from clueshelf.indexer import index_once
from clueshelf.models import SearchChunk
from clueshelf.search import sync_save
from sqlalchemy import select


def test_indexer_persists_vectors_and_rejects_deleted_chunk(system, monkeypatch):
    client, factory = system
    item = add(client, title="測試", author_text="日文食譜")
    monkeypatch.setattr("clueshelf.indexer.is_available", lambda: True)
    monkeypatch.setattr("clueshelf.indexer.embed", lambda texts, kind: [[1.0] + [0.0] * 383 for _ in texts])
    assert index_once(factory)
    with factory() as session:
        assert all(row.embedding_model == MODEL_NAME for row in session.scalars(select(SearchChunk)))
    assert not index_once(factory)
    client.patch(f"/api/v1/saves/{item['id']}", json={"version": 1, "author_text": "全新文字"})
    def deleting(texts, kind):
        client.delete(f"/api/v1/saves/{item['id']}?version=2")
        return [[1.0] + [0.0] * 383 for _ in texts]
    monkeypatch.setattr("clueshelf.indexer.embed", deleting)
    assert index_once(factory)
    with factory() as session:
        assert list(session.scalars(select(SearchChunk))) == []


def test_indexer_offline_preserves_pending_and_limits_failures(system, monkeypatch):
    client, factory = system
    add(client, title="測試")
    monkeypatch.setattr("clueshelf.indexer.is_available", lambda: False)
    assert not index_once(factory)
    monkeypatch.setattr("clueshelf.indexer.is_available", lambda: True)
    def broken(texts, kind):
        raise EmbeddingUnavailable("broken model")
    monkeypatch.setattr("clueshelf.indexer.embed", broken)
    assert index_once(factory) and index_once(factory) and index_once(factory)
    assert not index_once(factory)
