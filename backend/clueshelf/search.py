"""Owner-scoped multilingual retrieval over provenance-labelled content chunks."""
from collections import Counter
from hashlib import sha256
import math
import re
import threading
import unicodedata

import numpy as np
from sqlalchemy import func, literal_column, select, text
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


def eligible_ids(session, owner_id, platform=None, topics=None, tags=None):
    """(id, created_at) of searchable saves. Unfiltered searches must not load or classify every save."""
    if topics or tags:
        return [(save.id, save.created_at) for save in eligible_saves(session, owner_id, platform, topics, tags)]
    statement = select(Save.id, Save.created_at).where(Save.owner_id == owner_id, Save.duplicate_of.is_(None))
    if platform:
        statement = statement.where(Save.platform == platform)
    return [tuple(row) for row in session.execute(statement)]


def _snippet(value, tokens):
    folded = normalize(value)
    positions = [folded.find(token) for token in tokens if folded.find(token) >= 0]
    start = max(0, min(positions, default=0) - 35)
    return ("…" if start else "") + value[start:start + 180] + ("…" if start + 180 < len(value) else "")


def relaxed_terms(tokens):
    """Latin words and CJK bigrams, for sentences that contain no spaces to split on."""
    terms = []
    for token in tokens:
        for run in re.findall(r"[a-z0-9]+|[^\Wa-z0-9_]+", token):
            if run[0].isascii():
                if len(run) >= 2:
                    terms.append(run)
            elif len(run) <= 2:
                terms.append(run)
            else:
                terms.extend(run[index:index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(terms))


def _relaxed_keyword(session, eligible, tokens):
    """Fallback when no save contains every token: rank by rarity-weighted partial matches.

    A save needs at least two matched terms carrying 60% of the query's matchable weight, so one
    shared common word is not a hit.
    """
    terms = relaxed_terms(tokens)
    if len(terms) < 2:
        return []
    allowed = set(eligible)
    matches, weights = {}, {}
    for term in terms:
        rows = [row for row in session.execute(select(SearchChunk.id, SearchChunk.save_id).where(SearchChunk.normalized_text.contains(term, autoescape=True))) if row.save_id in allowed]
        saves = {row.save_id for row in rows}
        if not saves:
            continue
        weights[term] = math.log(1 + len(allowed) / len(saves))
        for row in rows:
            matches.setdefault(row.save_id, {}).setdefault(row.id, set()).add(term)
    total = sum(weights.values())
    ranked = []
    for save_id, chunks_hit in matches.items():
        matched = set().union(*chunks_hit.values())
        score = sum(weights[term] for term in matched)
        if len(matched) >= 2 and score >= 0.6 * total:
            best = max(chunks_hit, key=lambda chunk_id: (sum(weights[term] for term in chunks_hit[chunk_id]), -chunk_id))
            ranked.append((score, save_id, best, matched))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    ranked = ranked[:200]
    rows = {row.id: row for row in session.execute(select(SearchChunk.id, SearchChunk.field, SearchChunk.text).where(SearchChunk.id.in_([item[2] for item in ranked])))}
    return [{"save_id": save_id, "score": float(score), "match_field": rows[best].field, "match_text": _snippet(rows[best].text, sorted(matched, key=lambda term: -weights[term]))} for score, save_id, best, matched in ranked]


def _keyword(session, eligible, tokens):
    if not tokens or not eligible:
        return []
    return _strict_keyword(session, eligible, tokens) or _relaxed_keyword(session, eligible, tokens)


def _strict_keyword(session, eligible, tokens):
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


_vectors_lock = threading.Lock()
_vectors = None


def _vector_index(session):
    """All valid chunk vectors as one normalized matrix, rebuilt only when the stored set changes."""
    global _vectors
    stored = (SearchChunk.embedding_model == EMBEDDING_MODEL, SearchChunk.embedding.is_not(None))
    key = (str(session.get_bind().url), *session.execute(select(func.count(), func.coalesce(func.max(SearchChunk.id), 0), func.coalesce(func.sum(SearchChunk.id), 0)).where(*stored)).one())
    with _vectors_lock:
        if _vectors is not None and _vectors[0] == key:
            return _vectors[1:]
        ids, saves, fields, vectors = [], [], [], []
        for row in session.execute(select(SearchChunk.id, SearchChunk.save_id, SearchChunk.field, SearchChunk.embedding).where(*stored)):
            if len(row.embedding) == DIMENSIONS:
                ids.append(row.id), saves.append(row.save_id), fields.append(row.field), vectors.append(row.embedding)
        matrix = np.asarray(vectors, dtype=np.float32).reshape(len(ids), DIMENSIONS)
        norms = np.linalg.norm(matrix, axis=1)
        valid = np.isfinite(matrix).all(axis=1) & (norms > 0)
        matrix = matrix[valid] / norms[valid, None]
        keep = np.flatnonzero(valid)
        # A bare topic name embeds identically for every save in that topic and would outrank real content.
        content = np.array([fields[index] != "topics" for index in keep], dtype=bool)
        _vectors = (key, [ids[index] for index in keep], [saves[index] for index in keep], matrix, content)
        return _vectors[1:]


def _semantic(session, eligible, vector):
    if vector is None or not eligible:
        return []
    if len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise ValueError("Query vector must contain 384 finite values")
    length = math.sqrt(sum(value * value for value in vector))
    if not length:
        raise ValueError("Query vector must be nonzero")
    ids, saves, matrix, content = _vector_index(session)
    if not ids:
        return []
    allowed = set(eligible)
    scores = matrix @ (np.asarray(vector, dtype=np.float32) / length)
    best = {}
    for index in np.argsort(-scores, kind="stable"):
        save_id = saves[index]
        if content[index] and save_id in allowed and save_id not in best:
            best[save_id] = (float(scores[index]), ids[index])
    ranked = sorted(((score, save_id, chunk_id) for save_id, (score, chunk_id) in best.items()), key=lambda item: (-item[0], item[1]))
    rows = {}
    chunk_ids = [item[2] for item in ranked]
    for offset in range(0, len(chunk_ids), 500):
        rows.update({row.id: row for row in session.execute(select(SearchChunk.id, SearchChunk.field, SearchChunk.text).where(SearchChunk.id.in_(chunk_ids[offset:offset + 500])))})
    return [{"save_id": save_id, "score": score, "match_field": rows[chunk_id].field, "match_text": _snippet(rows[chunk_id].text, [])} for score, save_id, chunk_id in ranked if chunk_id in rows]


def search(session, owner_id, q, *, platform=None, topics=None, tags=None, mode="keyword", limit=50, query_vector=None):
    if mode not in {"keyword", "semantic", "hybrid"}:
        raise ValueError("Unknown search mode")
    eligible = dict(eligible_ids(session, owner_id, platform, topics, tags))
    tokens = list(dict.fromkeys(normalize(q).split()))
    limit = max(1, min(50, limit))
    if not tokens:
        return [{"save_id": save_id, "score": 0.0, "match_field": "", "match_text": ""} for save_id, _ in sorted(eligible.items(), key=lambda item: (-item[1], item[0]))[:limit]]
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
