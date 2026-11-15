from collections.abc import Generator
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select, update, func
from sqlalchemy.orm import Session

from .database import database_url, make_engine, session_factory
from .models import Job, Save, SearchChunk, VideoAnalysis
from .video_models import VideoRequest, VideoView
from .ai import MODEL, PROMPT_VERSION
from .service import OWNER, create_save, get_save, revise
from .search import effective_topics, effective_tags, search, search_facets, sync_save
from .embeddings import EmbeddingUnavailable, MODEL_NAME, embed, is_available


class CreateSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=500)
    author_text: str = Field(default="", max_length=50000)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class EditSave(Revision):
    title: str | None = Field(default=None, max_length=500)
    author_text: str | None = Field(default=None, max_length=50000)
    manual_comments: str | None = Field(default=None, max_length=30000)

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.author_text is None and self.manual_comments is None:
            raise ValueError("至少提供標題或作者內文")
        return self


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    state: Literal["queued", "running", "done", "failed", "superseded"]
    attempts: int
    error: str | None


class SaveView(BaseModel):
    id: str
    owner_id: str
    platform: Literal["youtube", "instagram", "threads"]
    content_id: str
    url: str
    title: str
    author_text: str
    version: int
    status: Literal["queued", "processing", "needs_text", "ready", "failed"]
    created_at: float
    updated_at: float
    job: JobView | None
    source: dict | None
    analysis: dict | None
    manual_comments: str
    extraction_status: Literal["idle", "queued", "processing", "complete", "partial", "blocked", "failed"]
    ai_status: Literal["idle", "queued", "processing", "complete", "unavailable", "failed"]
    extraction_error: str | None
    ai_error: str | None
    duplicate_of: str | None
    effective_topics: list[str]
    effective_tags: list[str]
    manual_topics: list[str] | None
    manual_tags: list[str] | None


class SaveDetail(SaveView):
    video_analysis: VideoView | None


class Classification(Revision):
    topics: list[str] | None = Field(default=None, max_length=30)
    tags: list[str] | None = Field(default=None, max_length=30)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value):
        if value is None:
            return value
        if any(not tag.strip() or len(tag.strip()) > 60 for tag in value):
            raise ValueError("標籤不可空白或超過 60 字")
        return list(dict.fromkeys(tag.strip() for tag in value))

    @model_validator(mode="after")
    def has_classification(self):
        if not self.model_fields_set.intersection({"topics", "tags"}):
            raise ValueError("請提供主題或標籤")
        return self


class TitleSelection(Revision):
    mode: Literal["original", "ai"]


class CreateResult(BaseModel):
    save: SaveDetail
    duplicate: bool


def view(session, save):
    job = session.scalar(select(Job).where(Job.save_id == save.id, Job.version == save.version))
    return SaveView(**{name: getattr(save, name) for name in SaveView.model_fields if name not in {"job", "effective_topics", "effective_tags"}}, job=JobView.model_validate(job) if job else None, effective_topics=effective_topics(save), effective_tags=effective_tags(save))


def detail(session, save):
    video = session.get(VideoAnalysis, save.id) if save.platform == "youtube" else None
    return SaveDetail(**view(session, save).model_dump(), video_analysis=VideoView.model_validate(video) if video else None)


def create_app(factory=None):
    app = FastAPI(title="ClueShelf API", version="0.1.0")
    factory = factory or session_factory(make_engine(database_url()))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_browser_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or origin and origin not in {"http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:8000", "http://localhost:8000"}:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "本地版本不接受外部網站的寫入請求。"}, status_code=403)
        return await call_next(request)

    def session() -> Generator[Session, None, None]:
        with factory() as s:
            yield s

    def require(s, save_id):
        save = get_save(s, save_id)
        if save is None:
            raise HTTPException(404, "找不到收藏。")
        return save

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "phase": "sources-and-ai", "ai_enabled": True, "extraction_enabled": True, "model": MODEL, "prompt_version": PROMPT_VERSION}

    @app.get("/api/v1/saves", response_model=list[SaveView])
    def list_saves(s: Session = Depends(session)):
        saves = s.scalars(select(Save).where(Save.owner_id == OWNER).order_by(Save.created_at.desc())).all()
        return [view(s, save) for save in saves]

    @app.post("/api/v1/saves", response_model=CreateResult)
    def add_save(body: CreateSave, response: Response, s: Session = Depends(session)):
        try:
            save, duplicate = create_save(s, body.url, body.title, body.author_text)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        response.status_code = 200 if duplicate else 201
        return CreateResult(save=detail(s, save), duplicate=duplicate)

    @app.get("/api/v1/saves/{save_id}", response_model=SaveDetail)
    def read_save(save_id: str, s: Session = Depends(session)):
        return detail(s, require(s, save_id))

    @app.post("/api/v1/saves/{save_id}/video-analysis", response_model=SaveDetail, status_code=202)
    def start_video_analysis(save_id: str, body: VideoRequest, s: Session = Depends(session)):
        s.connection().exec_driver_sql("BEGIN IMMEDIATE")
        save = require(s, save_id)
        if save.platform != "youtube" or save.duplicate_of:
            raise HTTPException(422, "只有 YouTube 影片收藏可解析。")
        if body.mode == "transcribe" and not body.audio_authorized:
            raise HTTPException(422, "請先確認你已獲准下載此影片的音訊。")
        video = s.get(VideoAnalysis, save.id)
        if video and video.state in {"queued", "running"}:
            if video.mode != body.mode:
                raise HTTPException(409, "這支影片已有解析工作，請等完成後再操作。")
        else:
            now = time.time()
            if video is None:
                video = VideoAnalysis(save_id=save.id)
                s.add(video)
            video.mode, video.state, video.available_at = body.mode, "queued", now
            video.attempts, video.error = 0, None
            save.updated_at = now
        s.commit()
        return detail(s, save)

    @app.patch("/api/v1/saves/{save_id}/classification", response_model=SaveDetail)
    def classify(save_id: str, body: Classification, s: Session = Depends(session)):
        from .taxonomy import validate_assignment
        s.connection().exec_driver_sql("BEGIN IMMEDIATE")
        save = require(s, save_id)
        pending = s.scalar(select(Job).where(Job.save_id == save.id, Job.version == body.version, Job.state.in_(["queued", "running"])))
        pending_kind = pending.kind if pending else None
        values = {"version": body.version + 1}
        if "topics" in body.model_fields_set:
            try:
                values["manual_topics"] = validate_assignment(s, OWNER, "topic", body.topics, existing_names=effective_topics(save)) if body.topics is not None else None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        if "tags" in body.model_fields_set:
            try:
                values["manual_tags"] = validate_assignment(s, OWNER, "tag", body.tags, existing_names=effective_tags(save)) if body.tags is not None else None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        changed = s.execute(update(Save).where(Save.id == save_id, Save.owner_id == OWNER, Save.version == body.version).values(**values)).rowcount
        if not changed:
            s.rollback()
            raise HTTPException(409, "收藏已有更新，請重新載入。")
        s.expire(save)
        if pending_kind:
            from .service import enqueue
            s.execute(update(Job).where(Job.save_id == save.id, Job.state.in_(["queued", "running"])).values(state="superseded"))
            save.status = "queued"
            enqueue(s, save, kind=pending_kind)
        sync_save(s, save)
        s.commit()
        return detail(s, save)

    def index_stats(s):
        rows = s.execute(select(SearchChunk.embedding_model, func.count()).join(Save).where(Save.owner_id == OWNER, Save.duplicate_of.is_(None)).group_by(SearchChunk.embedding_model)).all()
        ready = sum(count for model, count in rows if model == MODEL_NAME)
        total = sum(count for _, count in rows)
        failed = s.scalar(select(func.count()).select_from(SearchChunk).join(Save).where(Save.owner_id == OWNER, Save.duplicate_of.is_(None), SearchChunk.embedding_model.is_(None), SearchChunk.embedding_attempts >= 3)) or 0
        return {"pending": total - ready - failed, "failed": failed, "ready": ready, "model_ready": is_available()}

    @app.get("/api/v1/search/facets")
    def facets(s: Session = Depends(session)):
        return {**search_facets(s, OWNER), "index": index_stats(s)}

    @app.get("/api/v1/search")
    def find(q: str = Query(default="", max_length=500), mode: Literal["keyword", "semantic", "hybrid"] = "keyword", platform: Literal["youtube", "instagram", "threads"] | None = None, topic: list[str] = Query(default=[]), tag: list[str] = Query(default=[]), limit: int = Query(default=50, ge=1, le=50), s: Session = Depends(session)):
        if len(topic) > 9 or len(tag) > 30 or any(len(value) > 60 for value in topic + tag):
            raise HTTPException(422, "篩選條件過多或過長。")
        vector, notice, used_mode = None, None, mode
        stats = index_stats(s)
        if mode != "keyword" and q.strip():
            if not stats["ready"]:
                notice, used_mode = "語意搜尋資料尚未就緒，這次先使用關鍵字搜尋。", "keyword"
            else:
                try:
                    vector = embed([q], kind="query")[0]
                    if stats["pending"] or stats["failed"]:
                        notice = "部分收藏仍在建立語意搜尋資料，結果可能尚未包含全部收藏。"
                except EmbeddingUnavailable:
                    notice, used_mode = "本機語意模型未就緒，這次先使用關鍵字搜尋。", "keyword"
        hits = search(s, OWNER, q, platform=platform, topics=topic, tags=tag, mode=used_mode, limit=limit, query_vector=vector)
        results = [{"save": view(s, get_save(s, hit["save_id"])), **{name: value for name, value in hit.items() if name != "save_id"}} for hit in hits]
        return {"results": results, "requested_mode": mode, "used_mode": used_mode, "notice": notice}

    @app.post("/api/v1/search/reindex")
    def reindex(s: Session = Depends(session)):
        saves = s.scalars(select(Save).where(Save.owner_id == OWNER)).all()
        for save in saves:
            sync_save(s, save)
        changed = s.execute(update(SearchChunk).where(SearchChunk.save_id.in_([save.id for save in saves]), SearchChunk.embedding_model.is_(None)).values(embedding_attempts=0, embedding_error=None)).rowcount
        s.commit()
        return {"queued": changed}

    @app.patch("/api/v1/saves/{save_id}", response_model=SaveDetail)
    def edit_save(save_id: str, body: EditSave, s: Session = Depends(session)):
        original = require(s, save_id)
        if body.manual_comments is not None and original.platform != "threads":
            raise HTTPException(422, "只有 Threads 收藏可補充留言。")
        save = revise(s, original, body.version, body.title, body.author_text, body.manual_comments)
        if save is None:
            raise HTTPException(409, "收藏已有更新，請重新載入後再修改。")
        return detail(s, save)

    @app.post("/api/v1/saves/{save_id}/retry", response_model=SaveDetail)
    def retry(save_id: str, body: Revision, s: Session = Depends(session)):
        save = revise(s, require(s, save_id), body.version, kind="pipeline")
        if save is None:
            raise HTTPException(409, "收藏已有更新，請重新載入後再重試。")
        return detail(s, save)

    @app.post("/api/v1/saves/{save_id}/read", response_model=SaveDetail)
    def reread(save_id: str, body: Revision, s: Session = Depends(session)):
        return retry(save_id, body, s)

    @app.post("/api/v1/saves/{save_id}/analyze", response_model=SaveDetail)
    def analyze_save(save_id: str, body: Revision, s: Session = Depends(session)):
        save = revise(s, require(s, save_id), body.version, kind="analyze")
        if save is None:
            raise HTTPException(409, "收藏已有更新，請重新載入。")
        return detail(s, save)

    @app.post("/api/v1/saves/{save_id}/title", response_model=SaveDetail)
    def select_title(save_id: str, body: TitleSelection, s: Session = Depends(session)):
        from sqlalchemy import update
        save = require(s, save_id)
        if save.status in {"queued", "processing"}:
            raise HTTPException(409, "請等待目前處理完成再切換標題。")
        if body.mode == "ai" and save.ai_status != "complete":
            raise HTTPException(422, "目前內容尚無有效的 AI 標題，請先重新整理。")
        chosen = (save.source or {}).get("original_title") if body.mode == "original" else (save.analysis or {}).get("suggested_title")
        if not chosen:
            raise HTTPException(422, "尚無可用的標題。")
        changed = s.execute(update(Save).where(Save.id == save.id, Save.owner_id == OWNER, Save.version == body.version).values(title=chosen, title_manual=False, title_mode=body.mode, version=body.version + 1)).rowcount
        if not changed:
            s.rollback()
            raise HTTPException(409, "收藏已有更新，請重新載入。")
        s.expire(save)
        sync_save(s, save)
        s.commit()
        return detail(s, save)

    @app.delete("/api/v1/saves/{save_id}", status_code=204)
    def remove_save(save_id: str, version: int = Query(ge=1), s: Session = Depends(session)):
        require(s, save_id)
        drafts = s.scalars(select(Save).where(Save.owner_id == OWNER, Save.duplicate_of == save_id)).all()
        changed = s.execute(delete(Save).where(Save.id == save_id, Save.owner_id == OWNER, Save.version == version)).rowcount
        if not changed:
            s.rollback()
            raise HTTPException(409, "收藏已有更新，請重新載入後再刪除。")
        for draft in drafts:
            s.expire(draft, ["duplicate_of"])
            sync_save(s, draft)
        s.commit()
        return Response(status_code=204)

    from .youtube_api import create_router
    app.include_router(create_router(factory))
    from .taxonomy_api import create_router as taxonomy_router
    from .browse_api import create_router as browse_router
    app.include_router(taxonomy_router(factory))
    app.include_router(browse_router(factory))
    return app


app = create_app()
