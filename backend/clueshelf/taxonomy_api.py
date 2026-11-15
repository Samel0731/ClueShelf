"""Local API for canonical classifications and explicit suggestion approval."""
import time
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from sqlalchemy import select
from .service import OWNER
from .models import Save
from .taxonomy_models import Taxon, TaxonomySuggestionJob
from .taxonomy import seed_defaults, catalog_version, create_taxon, item_view, catalog_views, affected_saves, edit_taxon, merge_taxa, effective_names, sync_classifications
from .taxonomy_suggestions import latest, job_view, request_job

Template = Literal["generic", "recipe", "restaurant", "travel", "music", "resources", "event"]


class NewTaxon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["topic", "tag"]
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=1000)
    template: Template = "generic"
    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("分類名稱不可空白")
        return value.strip()


class EditTaxon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=1000)
    template: Template | None = None
    archived: bool | None = None
    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("分類名稱不可空白")
        return value.strip() if value is not None else None


class Preview(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    target_id: str | None = None


class Merge(BaseModel):
    version: int = Field(ge=1)
    target_id: str
    target_version: int = Field(ge=1)


class ApplyProposal(BaseModel):
    proposal_index: int = Field(ge=0, le=9)
    save_ids: list[str] = Field(default_factory=list, max_length=30)


def create_router(factory):
    router = APIRouter(prefix="/api/v1/taxonomy", tags=["taxonomy"])
    def require(session, identity):
        item = session.get(Taxon, identity)
        if item is None or item.owner_id != OWNER:
            raise HTTPException(404, "找不到分類。")
        return item
    def begin(session):
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        seed_defaults(session, OWNER)
    def check_version(item, expected):
        if item.version != expected or item.merged_into:
            raise HTTPException(409, "分類已有更新，請重新載入。")

    @router.get("")
    def catalog():
        with factory() as session:
            begin(session)
            rows = list(session.scalars(select(Taxon).where(Taxon.owner_id == OWNER).order_by(Taxon.kind.desc(), Taxon.name)))
            result = {"items": catalog_views(session, rows), "version": catalog_version(session)}
            session.commit()
            return result

    @router.post("")
    def create(body: NewTaxon):
        with factory() as session:
            begin(session)
            try:
                item = create_taxon(session, OWNER, body.kind, body.name, body.description, body.template)
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            result = item_view(session, item)
            session.commit()
            return result

    @router.post("/suggestions")
    def suggest():
        with factory() as session:
            begin(session)
            job = request_job(session, OWNER)
            result = job_view(job)
            session.commit()
            return result

    @router.get("/suggestions")
    def suggestions():
        with factory() as session:
            return job_view(latest(session, OWNER))

    @router.post("/suggestions/{identity}/apply")
    def apply(identity: str, body: ApplyProposal):
        with factory() as session:
            begin(session)
            job = session.get(TaxonomySuggestionJob, identity)
            if job is None or job.owner_id != OWNER:
                raise HTTPException(404, "找不到分類建議。")
            if job.state != "complete" or body.proposal_index >= len(job.result or []):
                raise HTTPException(409, "分類建議尚未完成或已失效。")
            if body.proposal_index in job.applied:
                raise HTTPException(409, "這個建議已經套用。")
            proposal = job.result[body.proposal_index]
            allowed = set(proposal["save_ids"])
            if not set(body.save_ids).issubset(allowed):
                raise HTTPException(422, "只能套用預覽中的收藏。")
            if proposal["kind"] == "new_topic":
                if not body.save_ids:
                    raise HTTPException(422, "請選擇至少一筆收藏。")
                saves = list(session.scalars(select(Save).where(Save.id.in_(body.save_ids), Save.owner_id == OWNER)))
                if len(saves) != len(set(body.save_ids)) or any(save.status in {"queued", "processing"} for save in saves):
                    raise HTTPException(409, "部分收藏仍在整理或已有變更，請稍後再試。")
                try:
                    item = create_taxon(session, OWNER, "topic", proposal["name"], proposal.get("description", ""))
                except ValueError as error:
                    raise HTTPException(409, str(error)) from None
                from .search import sync_save
                for save in saves:
                    save.manual_topics = list(dict.fromkeys([*effective_names(session, save, "topic"), item.name]))
                    save.version += 1
                    save.updated_at = time.time()
                    sync_save(session, save)
                applied = len(saves)
            else:
                item = require(session, proposal["target_id"])
                for taxon_id, version in proposal.get("versions", {}).items():
                    check_version(require(session, taxon_id), version)
                try:
                    for source_id in proposal["source_ids"]:
                        merge_taxa(session, require(session, source_id), item)
                except ValueError as error:
                    raise HTTPException(409, str(error)) from None
                applied = len(proposal["source_ids"])
            job.applied = [*job.applied, body.proposal_index]
            result = {"applied": applied, "taxon": item_view(session, item)}
            session.commit()
            return result

    @router.post("/{identity}/preview")
    def preview(identity: str, body: Preview):
        with factory() as session:
            item = require(session, identity)
            saves = affected_saves(session, item)
            target = require(session, body.target_id) if body.target_id else None
            return {"count": len(saves), "saves": [{"id": save.id, "title": save.title} for save in saves[:30]], "source": item_view(session, item), "target": item_view(session, target) if target else None}

    @router.patch("/{identity}")
    def edit(identity: str, body: EditTaxon):
        with factory() as session:
            begin(session)
            item = require(session, identity)
            check_version(item, body.version)
            try:
                edit_taxon(session, item, body.model_dump(exclude_unset=True, exclude={"version"}, exclude_none=True))
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            result = item_view(session, item)
            session.commit()
            return result

    @router.post("/{identity}/merge")
    def merge(identity: str, body: Merge):
        with factory() as session:
            begin(session)
            source, target = require(session, identity), require(session, body.target_id)
            check_version(source, body.version)
            check_version(target, body.target_version)
            try:
                merge_taxa(session, source, target)
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            result = item_view(session, target)
            session.commit()
            return result
    return router
