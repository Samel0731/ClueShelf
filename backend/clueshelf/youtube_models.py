"""Official account linkage is separate from saved content ownership."""
from sqlalchemy import ForeignKey, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class YouTubeConnection(Base):
    __tablename__ = "youtube_connections"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, unique=True)
    channel_id: Mapped[str] = mapped_column(String)
    channel_title: Mapped[str] = mapped_column(Text)
    playlist_id: Mapped[str] = mapped_column(String)
    token_key: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    last_complete_scan_at: Mapped[float | None]


class YouTubeOAuthState(Base):
    __tablename__ = "youtube_oauth_states"
    digest: Mapped[str] = mapped_column(String, primary_key=True)
    browser_digest: Mapped[str] = mapped_column(String)
    verifier_key: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float]


class YouTubeSync(Base):
    __tablename__ = "youtube_syncs"
    __table_args__ = (Index("youtube_sync_claim", "state", "available_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("youtube_connections.id"))
    token_key: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    cursor: Mapped[str | None] = mapped_column(Text)
    cursor_restarts: Mapped[int] = mapped_column(default=0)
    read_count: Mapped[int] = mapped_column(default=0)
    new_count: Mapped[int] = mapped_column(default=0)
    existing_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    failure_count: Mapped[int] = mapped_column(default=0)
    skip_reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[float | None]
    lease_token: Mapped[str | None] = mapped_column(String)
    available_at: Mapped[float]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[float]
    updated_at: Mapped[float]


class YouTubeSource(Base):
    __tablename__ = "youtube_sources"
    connection_id: Mapped[str] = mapped_column(ForeignKey("youtube_connections.id"), primary_key=True)
    video_id: Mapped[str] = mapped_column(String, primary_key=True)
    save_id: Mapped[str | None] = mapped_column(ForeignKey("saves.id", ondelete="SET NULL"))
    first_seen_at: Mapped[float]
    last_seen_at: Mapped[float]
    sync_id: Mapped[str] = mapped_column(ForeignKey("youtube_syncs.id"))
    source_status: Mapped[str] = mapped_column(String, default="seen")
