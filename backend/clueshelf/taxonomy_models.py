"""Canonical classifications and human-reviewed AI organization suggestions."""
from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Taxon(Base):
    __tablename__ = "taxa"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "normalized_name"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String, default="generic")
    archived: Mapped[bool] = mapped_column(default=False)
    merged_into: Mapped[str | None] = mapped_column(ForeignKey("taxa.id"))
    version: Mapped[int] = mapped_column(default=1)


class TaxonAlias(Base):
    __tablename__ = "taxon_aliases"
    owner_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    taxon_id: Mapped[str] = mapped_column(ForeignKey("taxa.id"), index=True)


class SaveTaxon(Base):
    __tablename__ = "save_taxa"
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True)
    taxon_id: Mapped[str] = mapped_column(ForeignKey("taxa.id"), primary_key=True, index=True)
    origin: Mapped[str] = mapped_column(String, default="ai")


class TaxonomySuggestionJob(Base):
    __tablename__ = "taxonomy_suggestion_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, default="queued")
    created_at: Mapped[float]
    lease_until: Mapped[float | None]
    token: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[list | None] = mapped_column(JSON)
    applied: Mapped[list] = mapped_column(JSON, default=list)
