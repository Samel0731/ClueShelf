"""Durable ten-minute result snapshots for paged collection exploration."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("browse_snapshots", sa.Column("id", sa.String(), primary_key=True), sa.Column("owner_id", sa.String(), nullable=False), sa.Column("filters", sa.JSON(), nullable=False), sa.Column("hits", sa.JSON(), nullable=False), sa.Column("requested_mode", sa.String(), nullable=False), sa.Column("used_mode", sa.String(), nullable=False), sa.Column("notice", sa.String()), sa.Column("created_at", sa.Float(), nullable=False), sa.Column("expires_at", sa.Float(), nullable=False))
    op.create_index("ix_browse_snapshots_owner_id", "browse_snapshots", ["owner_id"])
    op.create_index("browse_snapshot_expiry", "browse_snapshots", ["expires_at"])


def downgrade():
    op.drop_table("browse_snapshots")

