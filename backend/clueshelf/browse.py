"""Paged projections and bounded classification graphs over one result scope."""
import base64
from hashlib import sha256
import json
import math
import time
from uuid import uuid4

from sqlalchemy import select, func, delete, and_, Integer
from sqlalchemy.orm import aliased

from .models import Save, SearchChunk
from .browse_models import BrowseSnapshot
from .taxonomy_models import Taxon, SaveTaxon
from .taxonomy import catalog_version
from .search import _keyword, _semantic, normalize
from .embeddings import embed, is_available, EmbeddingUnavailable, MODEL_NAME

UNCLASSIFIED = "unclassified"
TTL = 600


class ScopeError(ValueError):
    def __init__(self, message, status=422):
        self.status = status
        super().__init__(message)


def canonical_filters(q="", mode="hybrid", platform=None, topics=(), tags=()):
    return {"q": q.strip(), "mode": mode, "platform": platform, "topics": sorted(set(topics)), "tags": sorted(set(tags))}


def base_query(owner):
    return select(Save.id).where(Save.owner_id == owner, Save.duplicate_of.is_(None))


def eligible_ids(session, owner, filters):
    query = base_query(owner)
    if filters["platform"]:
        query = query.where(Save.platform == filters["platform"])
    for kind, values in (("topic", filters["topics"]), ("tag", filters["tags"])):
        for identity in values:
            query = query.where(Save.id.in_(select(SaveTaxon.save_id).join(Taxon, Taxon.id == SaveTaxon.taxon_id).where(Taxon.id == identity, Taxon.owner_id == owner, Taxon.kind == kind, Taxon.merged_into.is_(None))))
    return list(session.scalars(query))


def index_stats(session, owner):
    mine = base_query(owner)
    rows = session.execute(select(SearchChunk.embedding_model, func.count()).where(SearchChunk.save_id.in_(mine)).group_by(SearchChunk.embedding_model)).all()
    ready = sum(count for model, count in rows if model == MODEL_NAME)
    total = sum(count for _, count in rows)
    failed = session.scalar(select(func.count()).select_from(SearchChunk).where(SearchChunk.save_id.in_(mine), SearchChunk.embedding_model.is_(None), SearchChunk.embedding_attempts >= 3)) or 0
    return {"pending": total-ready-failed, "failed": failed, "ready": ready, "model_ready": is_available()}


def data_revision(session, owner):
    row = session.execute(select(func.count(), func.coalesce(func.sum(Save.version), 0), func.coalesce(func.sum(Save.updated_at), 0), func.coalesce(func.sum((Save.ai_status == "complete").cast(Integer)), 0)).where(Save.owner_id == owner)).one()
    return sha256(json.dumps([*row, catalog_version(session, owner)], default=str).encode()).hexdigest()[:24]


def scope(session, owner, snapshot_id):
    row = session.get(BrowseSnapshot, snapshot_id)
    if not row or row.owner_id != owner:
        raise ScopeError("找不到這次瀏覽結果，請重新整理。", 404)
    if row.expires_at <= time.time():
        raise ScopeError("這次瀏覽結果已過期，請重新搜尋或更新收藏。", 410)
    return row


def make_scope(session, owner, filters):
    ids = eligible_ids(session, owner, filters)
    q, mode = filters["q"], filters["mode"]
    used_mode, notice, vector = mode, None, None
    if q and mode != "keyword":
        stats = index_stats(session, owner)
        if not stats["ready"]:
            used_mode, notice = "keyword", "語意搜尋資料尚未就緒，這次先使用關鍵字搜尋。"
        else:
            try:
                vector = embed([q], kind="query")[0]
                if stats["pending"] or stats["failed"]:
                    notice = "部分收藏仍在建立語意搜尋資料，結果可能尚未包含全部收藏。"
            except EmbeddingUnavailable:
                used_mode, notice = "keyword", "本機語意模型未就緒，這次先使用關鍵字搜尋。"
    if q:
        tokens = list(dict.fromkeys(normalize(q).split()))
        keyword = _keyword(session, ids, tokens) if used_mode != "semantic" else []
        semantic = _semantic(session, ids, vector) if used_mode != "keyword" else []
        if used_mode == "keyword":
            hits = keyword
        elif used_mode == "semantic":
            hits = semantic
        else:
            combined = {}
            for ranking in (keyword, semantic):
                for rank, hit in enumerate(ranking, 1):
                    entry = combined.setdefault(hit["save_id"], {**hit, "score": 0.0})
                    entry["score"] += 1/(60+rank)
            hits = sorted(combined.values(), key=lambda hit: (-hit["score"], hit["save_id"]))
    else:
        rows = session.execute(select(Save.id, Save.created_at).where(Save.id.in_(ids)).order_by(Save.created_at.desc(), Save.id)).all() if ids else []
        hits = [{"save_id": identity, "created_at": created, "match_field": "", "match_text": "", "score": 0.0} for identity, created in rows]
    now = time.time()
    session.execute(delete(BrowseSnapshot).where(BrowseSnapshot.expires_at <= now))
    result = BrowseSnapshot(id=str(uuid4()), owner_id=owner, filters=filters, hits=hits, requested_mode=mode, used_mode=used_mode, notice=notice, created_at=now, expires_at=now+TTL)
    session.add(result)
    session.flush()
    return result


def current_ids(session, owner, snapshot):
    ids = [hit["save_id"] for hit in snapshot.hits]
    return set(session.scalars(base_query(owner).where(Save.id.in_(ids)))) if ids else set()


def memberships(session, owner, ids):
    if not ids:
        return {}
    rows = session.execute(select(SaveTaxon.save_id, Taxon.id, Taxon.kind, Taxon.name).join(Taxon, Taxon.id == SaveTaxon.taxon_id).where(SaveTaxon.save_id.in_(ids), Taxon.owner_id == owner, Taxon.merged_into.is_(None)).order_by(Taxon.name, Taxon.id)).all()
    result = {}
    for save_id, identity, kind, name in rows:
        result.setdefault(save_id, []).append((identity, kind, name))
    return result


def brief_items(session, owner, hits):
    ids = [hit["save_id"] for hit in hits]
    if not ids:
        return []
    statement = select(Save.id, Save.platform, Save.url, Save.title, func.substr(Save.author_text, 1, 220).label("excerpt"), func.substr(func.coalesce(func.json_extract(Save.analysis, '$.summary'), ''), 1, 300).label("summary"), Save.created_at, Save.updated_at, Save.version, Save.status, Save.extraction_status, Save.ai_status, Save.duplicate_of).where(Save.owner_id == owner, Save.duplicate_of.is_(None), Save.id.in_(ids))
    rows = {row.id: dict(row._mapping) for row in session.execute(statement)}
    linked = memberships(session, owner, list(rows))
    result = []
    for hit in hits:
        row = rows.get(hit["save_id"])
        if row is None:
            continue
        values = linked.get(row["id"], [])
        row.update(topic_ids=[identity for identity, kind, _ in values if kind == "topic"], tag_ids=[identity for identity, kind, _ in values if kind == "tag"], effective_topics=[name for _, kind, name in values if kind == "topic"], effective_tags=[name for _, kind, name in values if kind == "tag"], match_field=hit.get("match_field", ""), match_text=hit.get("match_text", ""))
        if row["ai_status"] != "complete":
            row["summary"] = ""
        result.append(row)
    return result


def facets(session, owner, ids):
    if not ids:
        return {"topics": [], "tags": []}
    # Aggregate the filtered membership set first. Joining the full catalog before
    # grouping makes SQLite repeatedly scan a large IN list for every taxon.
    counts = select(SaveTaxon.taxon_id, func.count().label("count")).where(SaveTaxon.save_id.in_(ids)).group_by(SaveTaxon.taxon_id).subquery()
    rows = session.execute(select(Taxon.id, Taxon.kind, Taxon.name, counts.c.count).join(counts, Taxon.id == counts.c.taxon_id).where(Taxon.owner_id == owner, Taxon.merged_into.is_(None)).order_by(counts.c.count.desc(), Taxon.name, Taxon.id)).all()
    return {"topics": [{"id": identity, "name": name, "count": count} for identity, kind, name, count in rows if kind == "topic"], "tags": [{"id": identity, "name": name, "count": count} for identity, kind, name, count in rows if kind == "tag"]}


def encode_cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def decode_cursor(value):
    try:
        if len(value) > 2048:
            raise ValueError()
        decoded = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        if not isinstance(decoded, dict) or not isinstance(decoded.get("snapshot"), str) or not decoded["snapshot"] or len(decoded["snapshot"]) > 100:
            raise ValueError()
        return decoded
    except (ValueError, TypeError, UnicodeError):
        raise ScopeError("載入位置無效，請重新整理。") from None


def page_hits(snapshot, current, cursor, limit, branch=""):
    ordered = list(enumerate(snapshot.hits))
    offset = 0
    if cursor:
        value = decode_cursor(cursor)
        if value.get("snapshot") != snapshot.id or value.get("branch", "") != branch:
            raise ScopeError("載入位置與目前條件不同，請重新整理。")
        if ("after" in value) == bool(snapshot.filters["q"]):
            raise ScopeError("載入位置與目前搜尋方式不同，請重新整理。")
        if "after" in value:
            key = value["after"]
            if not isinstance(key, list) or len(key) != 2 or not isinstance(key[0], (int, float)) or not math.isfinite(key[0]) or not isinstance(key[1], str):
                raise ScopeError("載入位置無效。")
            ordered = [(position, hit) for position, hit in ordered if (-hit["created_at"], hit["save_id"]) > (-key[0], key[1])]
        else:
            offset = value.get("offset")
            if type(offset) is not int or offset < 0:
                raise ScopeError("載入位置無效。")
    available = [(position, hit) for position, hit in ordered if position >= offset and hit["save_id"] in current]
    selected_rows = available[:limit]
    selected = [hit for _, hit in selected_rows]
    next_cursor = None
    if len(selected_rows) < len(available) and selected:
        marker = {"after": [selected[-1]["created_at"], selected[-1]["save_id"]]} if not snapshot.filters["q"] else {"offset": selected_rows[-1][0]+1}
        next_cursor = encode_cursor({"snapshot": snapshot.id, "branch": branch, **marker})
    return selected, next_cursor


def browse(session, owner, filters, cursor=None, snapshot_id=None, limit=30):
    if cursor and not snapshot_id:
        snapshot_id = decode_cursor(cursor).get("snapshot")
    snapshot = scope(session, owner, snapshot_id) if snapshot_id else make_scope(session, owner, filters)
    if snapshot.filters != filters:
        raise ScopeError("載入位置與目前搜尋條件不同，請重新搜尋。")
    ids = current_ids(session, owner, snapshot)
    selected, next_cursor = page_hits(snapshot, ids, cursor, limit)
    return {"items": brief_items(session, owner, selected), "total": len(ids), "next_cursor": next_cursor, "snapshot_id": snapshot.id, **facets(session, owner, ids), "catalog_revision": catalog_version(session, owner), "data_revision": data_revision(session, owner), "index": index_stats(session, owner), "requested_mode": snapshot.requested_mode, "used_mode": snapshot.used_mode, "notice": snapshot.notice}


def graph(session, owner, snapshot_id):
    snapshot = scope(session, owner, snapshot_id)
    ids = current_ids(session, owner, snapshot)
    counts = facets(session, owner, ids)
    selected_topics, selected_tags = set(snapshot.filters["topics"]), set(snapshot.filters["tags"])
    topics = sorted(counts["topics"], key=lambda item: (item["id"] not in selected_topics, -item["count"], item["id"]))[:20]
    tags = sorted(counts["tags"], key=lambda item: (item["id"] not in selected_tags, -item["count"], item["id"]))[:40]
    nodes = [{"id": item["id"], "kind": kind, "label": item["name"], "count": item["count"]} for kind, items in (("topic", topics), ("tag", tags)) for item in items]
    visible = [node["id"] for node in nodes]
    edges = []
    if ids and visible:
        left, right = aliased(SaveTaxon), aliased(SaveTaxon)
        lt, rt = aliased(Taxon), aliased(Taxon)
        rows = session.execute(select(left.taxon_id, right.taxon_id, func.count(func.distinct(left.save_id))).join(right, and_(left.save_id == right.save_id, left.taxon_id < right.taxon_id)).join(lt, lt.id == left.taxon_id).join(rt, rt.id == right.taxon_id).where(left.save_id.in_(ids), left.taxon_id.in_(visible), right.taxon_id.in_(visible), ~and_(lt.kind == "topic", rt.kind == "topic")).group_by(left.taxon_id, right.taxon_id).order_by(func.count(func.distinct(left.save_id)).desc(), left.taxon_id, right.taxon_id)).all()
        edges = [{"id": f"{a}:{b}", "source": a, "target": b, "count": count} for a, b, count in rows]
    classified = set(session.scalars(select(SaveTaxon.save_id).where(SaveTaxon.save_id.in_(ids)))) if ids else set()
    missing = len(ids - classified)
    if missing:
        nodes.append({"id": UNCLASSIFIED, "kind": "unclassified", "label": "未分類收藏", "count": missing})
    return {"nodes": nodes, "edges": edges[:120], "truncated": {"topics": len(counts["topics"]) > 20, "tags": len(counts["tags"]) > 40, "edges": len(edges) > 120}, "data_revision": data_revision(session, owner)}


def expand(session, owner, snapshot_id, node_id, cursor=None, limit=30):
    snapshot = scope(session, owner, snapshot_id)
    ids = current_ids(session, owner, snapshot)
    if node_id == UNCLASSIFIED:
        linked = set(session.scalars(select(SaveTaxon.save_id).where(SaveTaxon.save_id.in_(ids)))) if ids else set()
        ids -= linked
    else:
        taxon = session.scalar(select(Taxon).where(Taxon.id == node_id, Taxon.owner_id == owner, Taxon.merged_into.is_(None)))
        if not taxon:
            raise ScopeError("找不到這個分類。", 404)
        linked = set(session.scalars(select(SaveTaxon.save_id).where(SaveTaxon.taxon_id == node_id, SaveTaxon.save_id.in_(ids)))) if ids else set()
        ids.intersection_update(linked)
    selected, next_cursor = page_hits(snapshot, ids, cursor, limit, node_id)
    return {"items": brief_items(session, owner, selected), "total": len(ids), "next_cursor": next_cursor}


def status(session, owner, ids):
    items = brief_items(session, owner, [{"save_id": identity} for identity in ids])
    found = {item["id"] for item in items}
    total = session.scalar(select(func.count()).select_from(Save).where(Save.owner_id == owner, Save.duplicate_of.is_(None))) or 0
    return {"items": items, "deleted_ids": [identity for identity in ids if identity not in found], "total": total, "data_revision": data_revision(session, owner), "index": index_stats(session, owner)}


def scope_facets(session, owner, snapshot_id):
    snapshot = scope(session, owner, snapshot_id)
    ids = current_ids(session, owner, snapshot)
    return {**facets(session, owner, ids), "total": len(ids), "catalog_revision": catalog_version(session, owner), "data_revision": data_revision(session, owner), "index": index_stats(session, owner)}
