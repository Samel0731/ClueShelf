"""Short-lived owner-scoped result sets shared by all collection views."""
from sqlalchemy import JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class BrowseSnapshot(Base):
    __tablename__ = "browse_snapshots"
    __table_args__ = (Index("browse_snapshot_expiry", "expires_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    filters: Mapped[dict] = mapped_column(JSON)
    hits: Mapped[list] = mapped_column(JSON)
    requested_mode: Mapped[str] = mapped_column(String)
    used_mode: Mapped[str] = mapped_column(String)
    notice: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float]
    expires_at: Mapped[float]

