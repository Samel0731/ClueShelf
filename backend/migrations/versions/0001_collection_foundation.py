"""Collection and durable job foundation."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("saves", sa.Column("id", sa.String(), primary_key=True), sa.Column("owner_id", sa.String(), nullable=False), sa.Column("platform", sa.String(), nullable=False), sa.Column("content_id", sa.String(), nullable=False), sa.Column("url", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=False), sa.Column("author_text", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False), sa.Column("updated_at", sa.Float(), nullable=False), sa.UniqueConstraint("owner_id", "platform", "content_id"))
    op.create_index("ix_saves_owner_id", "saves", ["owner_id"])
    op.create_table("jobs", sa.Column("id", sa.String(), primary_key=True), sa.Column("save_id", sa.String(), sa.ForeignKey("saves.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("available_at", sa.Float(), nullable=False), sa.Column("lease_until", sa.Float(), nullable=True), sa.Column("token", sa.String(), nullable=True), sa.Column("error", sa.Text(), nullable=True), sa.UniqueConstraint("save_id", "version"))
    op.create_index("job_claim", "jobs", ["state", "available_at"])


def downgrade():
    op.drop_table("jobs")
    op.drop_table("saves")
