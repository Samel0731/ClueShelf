"""Index the golden saves in a throwaway migrated database and score each search mode."""
import os
from pathlib import Path
import time

from alembic import command
from alembic.config import Config

from .. import embeddings
from ..database import make_engine, session_factory
from ..indexer import index_once
from ..models import Save
from ..search import search, sync_save
from .metrics import percentile, retrieval_metrics

OWNER = "eval"
MODES = ("keyword", "semantic", "hybrid")


def build_index(saves, workdir, *, embed=True):
    """Real migrations, so FTS triggers and schema match production.

    Only source text is indexed (no AI summary or tags). That keeps the run deterministic and
    LLM-free, and makes the scores a lower bound for the full pipeline.
    """
    path = Path(workdir) / "eval.db"
    if path.exists():
        path.unlink()
    url = f"sqlite:///{path.as_posix()}"
    previous = os.environ.get("CLUESHELF_DATABASE_URL")
    os.environ["CLUESHELF_DATABASE_URL"] = url
    try:
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("CLUESHELF_DATABASE_URL", None)
        else:
            os.environ["CLUESHELF_DATABASE_URL"] = previous
    engine = make_engine(url)
    factory = session_factory(engine)
    now = time.time()
    with factory() as session:
        for offset, item in enumerate(saves):
            source = {"original_title": item.get("original_title", ""), "author_text": item["author_text"], "comments": item.get("comments", [])}
            save = Save(id=item["id"], owner_id=OWNER, platform=item["platform"], content_id=item["id"], url=f"https://example.invalid/{item['id']}", title=item.get("original_title", ""), author_text=item["author_text"], status="ready", version=1, created_at=now + offset, updated_at=now + offset, ai_status="idle", analysis=None, source=source)
            session.add(save)
            session.flush()
            sync_save(session, save)
        session.commit()
    if embed:
        while index_once(factory):
            pass
    return engine, factory


def run(saves, queries, workdir, *, k=5):
    semantic_ready = embeddings.is_available()
    engine, factory = build_index(saves, workdir, embed=semantic_ready)
    modes = MODES if semantic_ready else ("keyword",)
    ranked = {mode: [] for mode in modes}
    latencies = {mode: [] for mode in modes}
    details = []
    try:
        with factory() as session:
            for query in queries:
                detail = {"id": query["id"], "query": query["query"], "kind": query.get("kind"), "relevant": query["relevant"], "first_relevant_rank": {}}
                for mode in modes:
                    started = time.perf_counter()
                    vector = embeddings.embed([query["query"]], "query")[0] if mode != "keyword" else None
                    results = [item["save_id"] for item in search(session, OWNER, query["query"], mode=mode, limit=50, query_vector=vector)]
                    latencies[mode].append(time.perf_counter() - started)
                    ranked[mode].append({"relevant": query["relevant"], "ranked": results})
                    detail["first_relevant_rank"][mode] = next((rank for rank, item in enumerate(results, start=1) if item in query["relevant"]), None)
                details.append(detail)
    finally:
        engine.dispose()
    return {
        "embedding_model": embeddings.MODEL_NAME if semantic_ready else None,
        "embedding_revision": embeddings.MODEL_REVISION if semantic_ready else None,
        "semantic_skipped": not semantic_ready,
        "saves": len(saves),
        "k": k,
        "modes": {mode: {**retrieval_metrics(ranked[mode], k), "latency_ms_p50": round(percentile(latencies[mode], 0.5) * 1000, 1), "latency_ms_p95": round(percentile(latencies[mode], 0.95) * 1000, 1)} for mode in modes},
        "queries": details,
    }
