"""Owner-scoped multilingual retrieval over provenance-labelled content chunks."""
from collections import Counter
from hashlib import sha256
import math
import unicodedata

from sqlalchemy import delete, literal_column, select, text
from sqlalchemy.orm import object_session

from .models import Save, SearchChunk, VideoAnalysis

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DIMENSIONS = 384


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower()


def effective_topics(save):
    session = object_session(save)
    if session is not None:
        from .taxonomy import effective_names
        return effective_names(session, save, "topic")
    manual = getattr(save, "manual_topics", None)
    return list(dict.fromkeys(manual if manual is not None else (save.analysis or {}).get("topics", [])))


def effective_tags(save):
    session = object_session(save)
    if session is not None:
        from .taxonomy import effective_names
        return effective_names(session, save, "tag")
    manual = getattr(save, "manual_tags", None)
    return list(dict.fromkeys(manual if manual is not None else (save.analysis or {}).get("tags", [])))


def content_fields(save):
    source = save.source or {}
    fields = [("display_title", save.title), ("original_title", source.get("original_title", "")), ("author_text", save.author_text)]
    if source.get("author_text") != save.author_text:
        fields.append(("original_author_text", source.get("author_text", "")))
    if save.ai_status == "complete":
        fields.append(("summary", (save.analysis or {}).get("summary", "")))
    fields.extend([("topics", " ".join(effective_topics(save))), ("tags", " ".join(effective_tags(save)))])
    if save.platform == "threads":
        fields.extend((f"threads_comment:{comment['source_id']}", comment["text"]) for comment in source.get("comments", []))
        fields.append(("manual_comments", save.manual_comments))
    if save.platform == "youtube" and (session := object_session(save)) is not None:
        video = session.get(VideoAnalysis, save.id)
        if video and video.result:
            for finding in video.result["findings"]:
                label = " ".join(filter(None, (finding["name"], finding["ticker"])))
                fields.append((f"video_{finding['kind']}", label))
    return [(field, value.strip()) for field, value in fields if value and value.strip()]


def chunks(value, size=400, overlap=80):
    for start in range(0, len(value), size - overlap):
        yield value[start:start + size]
        if start + size >= len(value):
            break


def sync_save(session, save):
    """Keep unchanged content vectors; changed/deleted chunks cannot remain searchable."""
    from .taxonomy import sync_classifications
    sync_classifications(session, save)
    existing = list(session.scalars(select(SearchChunk).where(SearchChunk.save_id == save.id)))
    wanted = {}
    if not save.duplicate_of:
        for field, value in content_fields(save):
            for piece in chunks(value):
                digest = sha256((field + "\0" + piece).encode()).hexdigest()
                wanted[(field, digest)] = piece
    for row in existing:
        key = (row.field, row.fingerprint)
        if key in wanted:
            wanted.pop(key)
        else:
            session.delete(row)
    for (field, digest), value in wanted.items():
        session.add(SearchChunk(save_id=save.id, field=field, text=value, normalized_text=normalize(value), fingerprint=digest, embedding=None, embedding_model=None))
    session.flush()


def eligible_saves(session, owner_id, platform=None, topics=None, tags=None):
    statement = select(Save).where(Save.owner_id == owner_id, Save.duplicate_of.is_(None))
    if platform:
        statement = statement.where(Save.platform == platform)
    required_topics = set(topics or [])
    required_tags = {normalize(tag) for tag in tags or []}
    return [save for save in session.scalars(statement) if required_topics.issubset(effective_topics(save)) and required_tags.issubset({normalize(tag) for tag in effective_tags(save)})]


def _snippet(value, tokens):
    folded = normalize(value)
    positions = [folded.find(token) for token in tokens if folded.find(token) >= 0]
    start = max(0, min(positions, default=0) - 35)
    return ("…" if start else "") + value[start:start + 180] + ("…" if start + 180 < len(value) else "")


def _keyword(session, eligible, tokens):
    if not tokens or not eligible:
        return []
    allowed = set(eligible)
    matched = {}
    for token in tokens:
        statement = select(SearchChunk).where(SearchChunk.save_id.in_(eligible))
        if len(token) >= 3:
            quoted = '"' + token.replace('"', '""') + '"'
            ids = select(literal_column("chunk_id")).select_from(text("search_fts")).where(text("search_fts MATCH :fts"))
            statement = statement.where(SearchChunk.id.in_(ids)).params(fts=quoted)
        else:
            statement = statement.where(SearchChunk.normalized_text.contains(token, autoescape=True))
        hits = list(session.scalars(statement))
        allowed.intersection_update(row.save_id for row in hits)
        for row in hits:
            matched.setdefault(row.save_id, {})[row.id] = row
        if not allowed:
            return []
    weights = {"display_title": 8, "original_title": 7, "tags": 6, "topics": 5, "author_text": 4, "original_author_text": 3, "summary": 2}
    results = []
    for save_id in allowed:
        rows = list(matched[save_id].values())
        def weight(row):
            return weights.get(row.field, 1) + sum(normalize(row.text).count(token) for token in tokens)
        # Prefer primary text as evidence over a generated tag that repeats the same word.
        evidence = {"display_title": 8, "original_title": 7, "author_text": 6, "original_author_text": 5, "summary": 3, "tags": 2, "topics": 1}
        best = max(rows, key=lambda row: (evidence.get(row.field, 4), weight(row)))
        results.append({"save_id": save_id, "score": float(sum(weight(row) for row in rows)), "match_field": best.field, "match_text": _snippet(best.text, tokens)})
    return sorted(results, key=lambda item: (-item["score"], item["save_id"]))


def _semantic(session, eligible, vector):
    if vector is None or not eligible:
        return []
    if len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise ValueError("Query vector must contain 384 finite values")
    length = math.sqrt(sum(value * value for value in vector))
    if not length:
        raise ValueError("Query vector must be nonzero")
    query = [value / length for value in vector]
    best = {}
    rows = session.scalars(select(SearchChunk).where(SearchChunk.save_id.in_(eligible), SearchChunk.embedding_model == EMBEDDING_MODEL, SearchChunk.embedding.is_not(None)))
    for row in rows:
        embedding = row.embedding
        if len(embedding) != DIMENSIONS or not all(math.isfinite(value) for value in embedding):
            continue
        norm = math.sqrt(sum(value * value for value in embedding))
        if not norm:
            continue
        score = sum(a * b for a, b in zip(query, embedding)) / norm
        if score > best.get(row.save_id, {}).get("score", float("-inf")):
            best[row.save_id] = {"save_id": row.save_id, "score": score, "match_field": row.field, "match_text": _snippet(row.text, [])}
    return sorted(best.values(), key=lambda item: (-item["score"], item["save_id"]))


def search(session, owner_id, q, *, platform=None, topics=None, tags=None, mode="keyword", limit=50, query_vector=None):
    if mode not in {"keyword", "semantic", "hybrid"}:
        raise ValueError("Unknown search mode")
    eligible = {save.id: save for save in eligible_saves(session, owner_id, platform, topics, tags)}
    tokens = list(dict.fromkeys(normalize(q).split()))
    limit = max(1, min(50, limit))
    if not tokens:
        return [{"save_id": save.id, "score": 0.0, "match_field": "", "match_text": ""} for save in sorted(eligible.values(), key=lambda save: (-save.created_at, save.id))[:limit]]
    keywords = _keyword(session, list(eligible), tokens) if mode != "semantic" or query_vector is None else []
    semantics = _semantic(session, list(eligible), query_vector) if mode != "keyword" else []
    if mode == "keyword" or query_vector is None:
        return keywords[:limit]
    if mode == "semantic":
        return semantics[:limit]
    combined = {}
    for ranking in (keywords, semantics):
        for rank, item in enumerate(ranking, start=1):
            entry = combined.setdefault(item["save_id"], {**item, "score": 0.0})
            entry["score"] += 1 / (60 + rank)
    return sorted(combined.values(), key=lambda item: (-item["score"], item["save_id"]))[:limit]


def search_facets(session, owner_id):
    saves = eligible_saves(session, owner_id)
    def counts(values):
        return [{"name": value, "count": count} for value, count in sorted(Counter(values).items(), key=lambda pair: (-pair[1], pair[0]))]
    return {"topics": counts(topic for save in saves for topic in effective_topics(save)), "tags": counts(tag for save in saves for tag in effective_tags(save)), "platforms": counts(save.platform for save in saves)}
