"""HTTP validation for lightweight collection exploration."""
from typing import Literal
from fastapi import APIRouter, Query, HTTPException, Response
from .service import OWNER
from . import browse as explorer


def create_router(factory):
    router = APIRouter(prefix="/api/v1", tags=["explore"])

    def run(response, operation):
        response.headers["Cache-Control"] = "no-store"
        try:
            with factory() as session:
                result = operation(session)
                session.commit()
                return result
        except explorer.ScopeError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/browse")
    def browse(response: Response, q: str = Query(default="", max_length=500), mode: Literal["keyword", "semantic", "hybrid"] = "hybrid", platform: Literal["youtube", "instagram", "threads"] | None = None, topic: list[str] = Query(default=[]), tag: list[str] = Query(default=[]), cursor: str | None = Query(default=None, max_length=2048), snapshot_id: str | None = None, limit: int = Query(default=30, ge=1, le=30)):
        if len(topic) > 20 or len(tag) > 30 or any(len(value) > 100 for value in topic+tag):
            raise HTTPException(422, "篩選條件過多或過長。")
        filters = explorer.canonical_filters(q, mode, platform, topic, tag)
        return run(response, lambda session: explorer.browse(session, OWNER, filters, cursor, snapshot_id, limit))

    @router.get("/browse/status")
    def status(response: Response, ids: list[str] = Query(default=[])):
        if len(ids) > 100 or any(len(identity) > 100 for identity in ids):
            raise HTTPException(422, "每次最多更新一百筆收藏。")
        return run(response, lambda session: explorer.status(session, OWNER, list(dict.fromkeys(ids))))

    @router.get("/browse/facets")
    def facets(response: Response, snapshot_id: str):
        return run(response, lambda session: explorer.scope_facets(session, OWNER, snapshot_id))

    @router.get("/graph")
    def graph(response: Response, snapshot_id: str):
        return run(response, lambda session: explorer.graph(session, OWNER, snapshot_id))

    @router.get("/graph/expand")
    def expand(response: Response, snapshot_id: str, node_id: str, cursor: str | None = Query(default=None, max_length=2048), limit: int = Query(default=30, ge=1, le=30)):
        return run(response, lambda session: explorer.expand(session, OWNER, snapshot_id, node_id, cursor, limit))

    return router
