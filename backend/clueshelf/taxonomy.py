"""Classification identity, aliases and effective memberships have one owner."""
from hashlib import sha256
import json
import unicodedata
from uuid import uuid4
from sqlalchemy import delete, func, select, update
from .models import Save
from .taxonomy_models import Taxon, TaxonAlias, SaveTaxon

DEFAULTS = [
    ("食譜", "料理材料、作法、備餐與冷凍餐", "recipe"),
    ("餐廳", "店家介紹、外食推薦或詢問吃飯地點", "restaurant"),
    ("旅遊", "景點與旅行行程", "travel"),
    ("音樂", "歌曲、歌手、翻唱、現場演唱與歌回", "music"),
    ("程式", "軟體、AI、LLM、MLOps 等技術", "resources"),
    ("語言學習", "語言教材或練習", "resources"),
    ("求職", "履歷、面試與職涯", "resources"),
    ("活動", "活動公告", "event"),
    ("其他", "暫時無法歸入已知主題的收藏", "generic"),
]


def normalize(value):
    return unicodedata.normalize("NFKC", value.strip()).lower()


def canonical(session, taxon):
    visited = set()
    while taxon is not None and taxon.merged_into:
        if taxon.id in visited:
            raise ValueError("分類合併形成循環。")
        visited.add(taxon.id)
        taxon = session.get(Taxon, taxon.merged_into)
    return taxon


def resolve(session, owner_id, kind, name):
    normalized = normalize(name)
    alias = session.get(TaxonAlias, (owner_id, kind, normalized))
    taxon = session.get(Taxon, alias.taxon_id) if alias else session.scalar(select(Taxon).where(Taxon.owner_id == owner_id, Taxon.kind == kind, Taxon.normalized_name == normalized))
    return canonical(session, taxon)


def add_alias(session, taxon, name):
    normalized = normalize(name)
    alias = session.get(TaxonAlias, (taxon.owner_id, taxon.kind, normalized))
    if alias is None:
        session.add(TaxonAlias(owner_id=taxon.owner_id, kind=taxon.kind, normalized_name=normalized, name=name, taxon_id=taxon.id))
    elif canonical(session, session.get(Taxon, alias.taxon_id)).id != taxon.id:
        raise ValueError("此名稱已被其他分類使用。")


def create_taxon(session, owner_id, kind, name, description="", template="generic"):
    name = name.strip()
    if not name or len(name) > 60:
        raise ValueError("分類名稱須為 1 至 60 字。")
    if resolve(session, owner_id, kind, name):
        raise ValueError("已有相同名稱或別名的分類。")
    taxon = Taxon(id=str(uuid4()), owner_id=owner_id, kind=kind, name=name, normalized_name=normalize(name), description=description, template=template, archived=False, version=1)
    session.add(taxon)
    session.flush()
    add_alias(session, taxon, name)
    session.flush()
    return taxon


def seed_defaults(session, owner_id="local-developer"):
    # Seed only missing defaults, never resurrect renamed, merged or archived ones.
    existing = set(session.scalars(select(TaxonAlias.normalized_name).where(TaxonAlias.owner_id == owner_id, TaxonAlias.kind == "topic", TaxonAlias.normalized_name.in_([normalize(row[0]) for row in DEFAULTS]))))
    for name, description, template in DEFAULTS:
        if normalize(name) not in existing and resolve(session, owner_id, "topic", name) is None:
            create_taxon(session, owner_id, "topic", name, description, template)


def raw_names(save, kind):
    field = "topics" if kind == "topic" else "tags"
    manual = getattr(save, "manual_" + field, None)
    return list(dict.fromkeys(manual if manual is not None else (save.analysis or {}).get(field, [])))


def effective_names(session, save, kind):
    names = []
    for value in raw_names(save, kind):
        taxon = resolve(session, save.owner_id, kind, value)
        if taxon and taxon.archived and session.get(SaveTaxon, (save.id, taxon.id)) is None:
            continue
        # Unknown legacy text remains visible until the migration/backfill resolves it.
        name = taxon.name if taxon else value
        if name not in names:
            names.append(name)
    return names


def sync_classifications(session, save):
    seed_defaults(session, save.owner_id)
    prior = {row.taxon_id for row in session.scalars(select(SaveTaxon).where(SaveTaxon.save_id == save.id))}
    wanted = {}
    if not save.duplicate_of:
        for kind in ("topic", "tag"):
            manual = getattr(save, "manual_topics" if kind == "topic" else "manual_tags", None) is not None
            for name in raw_names(save, kind):
                taxon = resolve(session, save.owner_id, kind, name)
                if taxon is None and (kind == "tag" or manual):
                    taxon = create_taxon(session, save.owner_id, kind, name)
                if taxon and (not taxon.archived or taxon.id in prior):
                    wanted[taxon.id] = "manual" if manual else "ai"
    for row in session.scalars(select(SaveTaxon).where(SaveTaxon.save_id == save.id)):
        if row.taxon_id not in wanted:
            session.delete(row)
        else:
            row.origin = wanted.pop(row.taxon_id)
    for identity, origin in wanted.items():
        session.add(SaveTaxon(save_id=save.id, taxon_id=identity, origin=origin))
    session.flush()


def validate_assignment(session, owner_id, kind, names, existing_names=()):
    existing = {taxon.id for name in existing_names if (taxon := resolve(session, owner_id, kind, name))}
    result = []
    for name in names:
        taxon = resolve(session, owner_id, kind, name)
        if taxon is None and kind == "tag":
            taxon = create_taxon(session, owner_id, kind, name)
        if taxon is None:
            raise ValueError("請先在分類管理建立這個主題。")
        if taxon.archived and taxon.id not in existing:
            raise ValueError("封存的分類不能加入新的收藏。")
        if taxon.name not in result:
            result.append(taxon.name)
    return result


def active_topics(session, owner_id):
    seed_defaults(session, owner_id)
    return [{"name": item.name, "description": item.description} for item in session.scalars(select(Taxon).where(Taxon.owner_id == owner_id, Taxon.kind == "topic", Taxon.archived.is_(False), Taxon.merged_into.is_(None)).order_by(Taxon.name))]


def filter_ai_names(session, owner_id, kind, names):
    result = []
    for name in names:
        taxon = resolve(session, owner_id, kind, name)
        if taxon and taxon.archived:
            continue
        if kind == "topic" and taxon is None:
            continue
        value = taxon.name if taxon else name
        if value not in result:
            result.append(value)
    return result


def catalog_version(session, owner_id="local-developer"):
    rows = session.execute(select(Taxon.id, Taxon.version, Taxon.name, Taxon.archived, Taxon.merged_into).where(Taxon.owner_id == owner_id).order_by(Taxon.id)).all()
    return sha256(json.dumps([tuple(row) for row in rows], ensure_ascii=False).encode()).hexdigest()


def item_view(session, item):
    count = session.scalar(select(func.count()).select_from(SaveTaxon).join(Save).where(SaveTaxon.taxon_id == item.id, Save.owner_id == item.owner_id, Save.duplicate_of.is_(None))) or 0
    aliases = list(session.scalars(select(TaxonAlias.name).where(TaxonAlias.taxon_id == item.id).order_by(TaxonAlias.name)))
    return {**{key: getattr(item, key) for key in ("id", "kind", "name", "description", "template", "archived", "merged_into", "version")}, "count": count, "aliases": aliases}


def catalog_views(session, rows, owner_id="local-developer"):
    counts = dict(session.execute(select(SaveTaxon.taxon_id, func.count()).join(Save).where(Save.owner_id == owner_id, Save.duplicate_of.is_(None)).group_by(SaveTaxon.taxon_id)).all())
    aliases = {}
    for identity, name in session.execute(select(TaxonAlias.taxon_id, TaxonAlias.name).where(TaxonAlias.owner_id == owner_id).order_by(TaxonAlias.name)):
        aliases.setdefault(identity, []).append(name)
    return [{**{key: getattr(item, key) for key in ("id", "kind", "name", "description", "template", "archived", "merged_into", "version")}, "count": counts.get(item.id, 0), "aliases": aliases.get(item.id, [])} for item in rows]


def affected_saves(session, item):
    return list(session.scalars(select(Save).join(SaveTaxon).where(SaveTaxon.taxon_id == item.id, Save.owner_id == item.owner_id).order_by(Save.created_at.desc(), Save.id)))


def rebuild_affected(session, saves):
    from .search import sync_save
    for save in saves:
        sync_save(session, save)


def edit_taxon(session, item, values):
    saves = affected_saves(session, item)
    if "name" in values and values["name"].strip() != item.name:
        name = values["name"].strip()
        conflict = resolve(session, item.owner_id, item.kind, name)
        if conflict and conflict.id != item.id:
            raise ValueError("此名稱已被其他分類或別名使用。")
        add_alias(session, item, item.name)
        item.name, item.normalized_name = name, normalize(name)
        add_alias(session, item, name)
    for key in ("description", "template", "archived"):
        if key in values:
            setattr(item, key, values[key])
    item.version += 1
    session.flush()
    rebuild_affected(session, saves)
    return item


def merge_taxa(session, source, target):
    if source.id == target.id or source.kind != target.kind or source.owner_id != target.owner_id:
        raise ValueError("只能合併相同種類的不同分類。")
    if source.merged_into or target.merged_into or target.archived:
        raise ValueError("請選擇啟用中的合併目標。")
    saves = affected_saves(session, source)
    source.merged_into, source.archived = target.id, True
    source.normalized_name = "merged:" + source.id
    source.version += 1
    target.version += 1
    for alias in session.scalars(select(TaxonAlias).where(TaxonAlias.taxon_id == source.id)):
        alias.taxon_id = target.id
    session.flush()
    rebuild_affected(session, saves)
    return target
