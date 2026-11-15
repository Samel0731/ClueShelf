import time

import pytest
from sqlalchemy import select

from clueshelf.database import Base, make_engine, session_factory
from clueshelf.models import Save, SearchChunk
from clueshelf.search import EMBEDDING_MODEL, chunks, effective_tags, search, search_facets, sync_save


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'search.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(chunk_id UNINDEXED, text, tokenize='trigram')")
        c.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS search_test_insert AFTER INSERT ON search_chunks BEGIN INSERT INTO search_fts(chunk_id,text) VALUES(new.id,new.normalized_text); END")
        c.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS search_test_delete AFTER DELETE ON search_chunks BEGIN DELETE FROM search_fts WHERE chunk_id=old.id; END")
    with session_factory(engine)() as session:
        yield session
    engine.dispose()


def save(db, identity, *, owner="me", title="", body="", platform="youtube", topics=None, tags=None, comments=None):
    item = Save(id=identity, owner_id=owner, platform=platform, content_id=identity, url="https://example.invalid/", title=title, author_text=body, status="ready", version=1, created_at=time.time(), updated_at=time.time(), ai_status="complete", analysis={"topics": topics or [], "tags": tags or [], "summary": ""}, source={"comments": comments or []})
    db.add(item)
    db.flush()
    sync_save(db, item)
    db.commit()
    return item


def test_short_chinese_japanese_and_cross_field_keywords(db):
    item = save(db, "a", title="京都の料理", body="不用烤箱的抹茶甜點", topics=["食譜"], tags=["免烤箱"])
    assert [r["save_id"] for r in search(db, "me", "京都")] == [item.id]
    assert search(db, "me", "抹茶甜點")[0]["match_field"] == "author_text"
    assert search(db, "me", "京都 食譜")[0]["save_id"] == item.id
    assert search(db, "me", "不存在") == []


def test_normalization_literal_queries_and_parameterized_short_patterns(db):
    save(db, "a", title="ＡＷＳ 日本語 100% _資料")
    assert search(db, "me", "aws")[0]["save_id"] == "a"
    assert search(db, "me", "日本語")[0]["save_id"] == "a"
    assert search(db, "me", "%")[0]["save_id"] == "a"
    assert search(db, "me", "_資料")[0]["save_id"] == "a"
    assert search(db, "me", "* OR") == []
    assert search(db, "me", '"') == []


def test_thread_comment_provenance_and_owner_scope(db):
    save(db, "a", platform="threads", body="台中哪裡有生魚片", tags=["棠記"], comments=[{"source_id": "reply1", "text": "推薦棠記生魚片", "likes": 57}])
    save(db, "private", owner="other", title="棠記生魚片")
    hits = search(db, "me", "棠記")
    assert len(hits) == 1 and hits[0]["save_id"] == "a"
    assert hits[0]["match_field"] == "threads_comment:reply1"
    assert "棠記" in hits[0]["match_text"]


def test_filters_use_manual_overrides_and_facets(db):
    item = save(db, "a", title="學習", topics=["程式"], tags=["LLM"])
    save(db, "b", title="學習", platform="instagram", topics=["語言學習"], tags=["日文"])
    item.manual_topics = ["語言學習"]
    item.manual_tags = []
    sync_save(db, item)
    db.commit()
    assert effective_tags(item) == []
    assert search(db, "me", "學習", topics=["程式"]) == []
    assert len(search(db, "me", "學習", topics=["語言學習"])) == 2
    assert search(db, "me", "學習", platform="instagram", tags=["日文"])[0]["save_id"] == "b"
    assert search_facets(db, "me")["topics"] == [{"name": "語言學習", "count": 2}]


def test_sync_preserves_vectors_and_removes_changed_text(db):
    item = save(db, "a", title="舊標題", body="保留的原文")
    chunk = db.scalar(select(SearchChunk).where(SearchChunk.field == "author_text"))
    chunk.embedding = [1.0] + [0.0] * 383
    chunk.embedding_model = EMBEDDING_MODEL
    db.commit()
    original_id = chunk.id
    item.title = "新標題"
    sync_save(db, item)
    db.commit()
    preserved = db.get(SearchChunk, original_id)
    assert preserved.embedding[0] == 1.0
    assert search(db, "me", "舊標題") == []
    assert search(db, "me", "新標題")[0]["save_id"] == "a"
    db.delete(item)
    db.commit()
    assert search(db, "me", "保留") == []


def test_semantic_and_hybrid_collapse_and_filter_before_ranking(db):
    save(db, "a", title="日本の冷凍料理", topics=["食譜"])
    save(db, "b", title="其他收藏", topics=["音樂"])
    save(db, "private", owner="other", title="料理")
    for row in db.scalars(select(SearchChunk)):
        row.embedding = [1.0] + [0.0] * 383
        row.embedding_model = EMBEDDING_MODEL
    db.commit()
    vector = [1.0] + [0.0] * 383
    assert len(search(db, "me", "備餐", mode="semantic", topics=["食譜"], query_vector=vector)) == 1
    assert search(db, "me", "料理", mode="hybrid", query_vector=vector)[0]["save_id"] == "a"
    assert search(db, "me", "不存在", mode="semantic", query_vector=None) == []


def test_duplicate_drafts_and_stale_summaries_not_indexed(db):
    item = save(db, "a", title="正文")
    duplicate = save(db, "b", title="草稿獨有")
    duplicate.duplicate_of = item.id
    sync_save(db, duplicate)
    item.analysis = {"summary": "過期摘要內容", "topics": [], "tags": []}
    item.ai_status = "unavailable"
    sync_save(db, item)
    db.commit()
    assert search(db, "me", "草稿") == []
    assert search(db, "me", "過期摘要") == []


def test_chunk_boundaries_preserve_overlapping_context():
    value = "日" * 900
    pieces = list(chunks(value))
    assert all(len(piece) <= 400 for piece in pieces)
    assert sum(len(piece) for piece in pieces) > len(value)
