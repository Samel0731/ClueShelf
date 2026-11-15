from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Save(Base):
    __tablename__ = "saves"
    __table_args__ = (UniqueConstraint("owner_id", "platform", "content_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    platform: Mapped[str] = mapped_column(String)
    content_id: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    author_text: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String, default="queued")
    created_at: Mapped[float]
    updated_at: Mapped[float]
    source: Mapped[dict | None] = mapped_column(JSON)
    analysis: Mapped[dict | None] = mapped_column(JSON)
    manual_comments: Mapped[str] = mapped_column(Text, default="")
    title_manual: Mapped[bool] = mapped_column(default=False)
    text_manual: Mapped[bool] = mapped_column(default=False)
    title_mode: Mapped[str] = mapped_column(String, default="auto")
    extraction_status: Mapped[str] = mapped_column(String, default="idle")
    ai_status: Mapped[str] = mapped_column(String, default="idle")
    extraction_error: Mapped[str | None] = mapped_column(Text)
    ai_error: Mapped[str | None] = mapped_column(Text)
    duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("saves.id", ondelete="SET NULL"))
    manual_topics: Mapped[list | None] = mapped_column(JSON)
    manual_tags: Mapped[list | None] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("save_id", "version"), Index("job_claim", "state", "available_at"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id", ondelete="CASCADE"))
    version: Mapped[int]
    state: Mapped[str] = mapped_column(String, default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[float]
    lease_until: Mapped[float | None]
    token: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String, default="pipeline")
    size_class: Mapped[str] = mapped_column(String, default="small")


class QueueSchedule(Base):
    __tablename__ = "queue_schedule"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(default=0)


class VideoAnalysis(Base):
    __tablename__ = "video_analyses"
    __table_args__ = (Index("video_analysis_claim", "state", "available_at"),)

    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[float]
    lease_until: Mapped[float | None]
    token: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[dict | None] = mapped_column(JSON)


class SearchChunk(Base):
    __tablename__ = "search_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String)
    embedding: Mapped[list | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String)
    embedding_attempts: Mapped[int] = mapped_column(default=0)
    embedding_error: Mapped[str | None] = mapped_column(Text)
