"""Add independent YouTube analysis jobs and results."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_analyses",
        sa.Column("save_id", sa.String(), sa.ForeignKey("saves.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Float(), nullable=False),
        sa.Column("lease_until", sa.Float()),
        sa.Column("token", sa.String()),
        sa.Column("error", sa.Text()),
        sa.Column("result", sa.JSON()),
    )
    op.create_index("video_analysis_claim", "video_analyses", ["state", "available_at"])


def downgrade():
    op.execute("DELETE FROM search_chunks WHERE field IN ('video_song', 'video_stock')")
    op.drop_table("video_analyses")
