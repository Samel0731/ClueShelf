import time
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError

from .links import parse_link
from .models import Job, Save, VideoAnalysis
from .search import sync_save

OWNER = "local-developer"


def analysis_size(save):
    """Estimate only the source text actually included in the bounded AI input."""
    from .ai import build_messages
    from .extraction import Comment
    import json

    comments = [Comment.model_validate(item) for item in (save.source or {}).get("comments", [])] if save.platform == "threads" else []
    if save.platform == "threads" and save.manual_comments:
        comments.insert(0, Comment(source_id="manual", text=save.manual_comments, likes=None))
    payload = json.loads(build_messages((save.source or {}).get("original_title", save.title), save.author_text, comments)[-1]["content"])
    length = len(payload["original_title"]) + len(payload["author_text"]) + sum(len(item["text"]) for item in payload["comments"])
    return "small" if length <= 1000 else "medium" if length <= 3000 else "large"


def enqueue(session, save, kind="pipeline"):
    if kind == "pipeline" and (save.source or {}).get("provider") == "youtube_api":
        kind = "analyze"
    session.add(Job(id=str(uuid4()), save_id=save.id, version=save.version, state="queued", attempts=0, available_at=time.time(), kind=kind, size_class=analysis_size(save)))
    if kind == "pipeline":
        save.extraction_status = "queued"
        save.extraction_error = None
    save.ai_status = "queued" if kind in {"pipeline", "analyze"} else "idle"
    save.ai_error = None


def get_save(session, save_id):
    return session.scalar(select(Save).where(Save.id == save_id, Save.owner_id == OWNER))


def create_save(session, url, title, author_text):
    platform, content_id, canonical = parse_link(url)
    query = select(Save).where(Save.owner_id == OWNER, Save.platform == platform, Save.content_id == content_id)
    existing = session.scalar(query)
    if existing:
        return existing, True
    now = time.time()
    save = Save(id=str(uuid4()), owner_id=OWNER, platform=platform, content_id=content_id, url=canonical, title=title.strip(), author_text=author_text.strip(), title_manual=bool(title.strip()), text_manual=bool(author_text.strip()), version=1, status="queued", created_at=now, updated_at=now)
    session.add(save)
    try:
        session.flush()
        enqueue(session, save)
        if platform == "youtube":
            session.add(VideoAnalysis(save_id=save.id, mode="text", state="queued", available_at=now))
        sync_save(session, save)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(query)
        if existing is None:
            raise
        return existing, True
    return save, False


def revise(session, save, expected_version, title=None, author_text=None, manual_comments=None, kind="analyze"):
    values = dict(version=expected_version + 1, status="queued", updated_at=time.time())
    if kind != "pipeline":
        values["extraction_status"] = case((Save.extraction_status.in_(["queued", "processing"]), "idle"), else_=Save.extraction_status)
    if title is not None:
        values["title"] = title.strip()
        values["title_manual"] = True
    if author_text is not None:
        values["author_text"] = author_text.strip()
        values["text_manual"] = True
    if manual_comments is not None:
        values["manual_comments"] = manual_comments.strip()
    changed = session.execute(update(Save).where(Save.id == save.id, Save.owner_id == OWNER, Save.version == expected_version).values(**values)).rowcount
    if not changed:
        session.rollback()
        return None
    session.execute(update(Job).where(Job.save_id == save.id, Job.state.in_(["queued", "running"])).values(state="superseded"))
    session.expire(save)
    enqueue(session, save, kind)
    sync_save(session, save)
    session.commit()
    return save
