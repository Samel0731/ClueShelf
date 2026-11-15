"""Canonical classification catalog and effective membership cache."""
from alembic import op
import sqlalchemy as sa
import json
import unicodedata
from uuid import uuid4
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("taxa", sa.Column("id", sa.String(), primary_key=True), sa.Column("owner_id", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False), sa.Column("name", sa.String(), nullable=False), sa.Column("normalized_name", sa.String(), nullable=False), sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("template", sa.String(), nullable=False, server_default="generic"), sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"), sa.Column("merged_into", sa.String(), sa.ForeignKey("taxa.id")), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.UniqueConstraint("owner_id", "kind", "normalized_name"))
    op.create_index("ix_taxa_owner_id", "taxa", ["owner_id"])
    op.create_table("taxon_aliases", sa.Column("owner_id", sa.String(), primary_key=True), sa.Column("kind", sa.String(), primary_key=True), sa.Column("normalized_name", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False), sa.Column("taxon_id", sa.String(), sa.ForeignKey("taxa.id"), nullable=False))
    op.create_index("ix_taxon_aliases_taxon_id", "taxon_aliases", ["taxon_id"])
    op.create_table("save_taxa", sa.Column("save_id", sa.String(), sa.ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True), sa.Column("taxon_id", sa.String(), sa.ForeignKey("taxa.id"), primary_key=True), sa.Column("origin", sa.String(), nullable=False, server_default="ai"))
    op.create_index("ix_save_taxa_taxon_id", "save_taxa", ["taxon_id"])
    op.create_table("taxonomy_suggestion_jobs", sa.Column("id", sa.String(), primary_key=True), sa.Column("owner_id", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False), sa.Column("lease_until", sa.Float()), sa.Column("token", sa.String()), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text()), sa.Column("result", sa.JSON()), sa.Column("applied", sa.JSON(), nullable=False))
    op.create_index("ix_taxonomy_suggestion_jobs_owner_id", "taxonomy_suggestion_jobs", ["owner_id"])
    connection = op.get_bind()
    taxa = sa.table("taxa", *[sa.column(name) for name in ("id", "owner_id", "kind", "name", "normalized_name", "description", "template", "archived", "version")])
    aliases = sa.table("taxon_aliases", *[sa.column(name) for name in ("owner_id", "kind", "normalized_name", "name", "taxon_id")])
    memberships = sa.table("save_taxa", *[sa.column(name) for name in ("save_id", "taxon_id", "origin")])
    identities = {}
    def intern(owner, kind, name, description="", template="generic"):
        key = (owner, kind, unicodedata.normalize("NFKC", name.strip()).lower())
        if key not in identities:
            identity = str(uuid4())
            connection.execute(taxa.insert().values(id=identity, owner_id=owner, kind=kind, name=name.strip(), normalized_name=key[2], description=description, template=template, archived=False, version=1))
            connection.execute(aliases.insert().values(owner_id=owner, kind=kind, normalized_name=key[2], name=name.strip(), taxon_id=identity))
            identities[key] = identity
        return identities[key]
    defaults = [("食譜", "料理材料、作法、備餐與冷凍餐", "recipe"), ("餐廳", "店家介紹、外食推薦或詢問吃飯地點", "restaurant"), ("旅遊", "景點與旅行行程", "travel"), ("音樂", "歌曲、歌手、翻唱、現場演唱與歌回", "music"), ("程式", "軟體、AI、LLM、MLOps 等技術", "resources"), ("語言學習", "語言教材或練習", "resources"), ("求職", "履歷、面試與職涯", "resources"), ("活動", "活動公告", "event"), ("其他", "暫時無法歸入已知主題的收藏", "generic")]
    owners = set(connection.execute(sa.text("SELECT DISTINCT owner_id FROM saves")).scalars()) | {"local-developer"}
    for owner in owners:
        for name, description, template in defaults:
            intern(owner, "topic", name, description, template)
    def decode(value, fallback):
        return json.loads(value) if isinstance(value, str) else value if value is not None else fallback
    for identity, owner, analysis, manual_topics, manual_tags, duplicate in connection.execute(sa.text("SELECT id,owner_id,analysis,manual_topics,manual_tags,duplicate_of FROM saves")):
        if duplicate:
            continue
        analysis = decode(analysis, {}) or {}
        for kind, field, manual in (("topic", "topics", manual_topics), ("tag", "tags", manual_tags)):
            values = decode(manual, None)
            origin = "manual" if values is not None else "ai"
            values = values if values is not None else analysis.get(field, [])
            seen = set()
            for name in values:
                if not isinstance(name, str) or not name.strip():
                    continue
                taxon = intern(owner, kind, name)
                if taxon not in seen:
                    connection.execute(memberships.insert().values(save_id=identity, taxon_id=taxon, origin=origin))
                    seen.add(taxon)


def downgrade():
    for name in ("taxonomy_suggestion_jobs", "save_taxa", "taxon_aliases", "taxa"):
        op.drop_table(name)
