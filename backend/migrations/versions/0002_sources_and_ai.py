"""Keep source text, comments and analysis separate from manual fields."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("saves") as batch:
        batch.add_column(sa.Column("source", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("analysis", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("manual_comments", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("title_manual", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("text_manual", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("title_mode", sa.String(), nullable=False, server_default="auto"))
        batch.add_column(sa.Column("extraction_status", sa.String(), nullable=False, server_default="idle"))
        batch.add_column(sa.Column("ai_status", sa.String(), nullable=False, server_default="idle"))
        batch.add_column(sa.Column("extraction_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ai_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("duplicate_of", sa.String(), nullable=True))
        batch.create_foreign_key("fk_save_duplicate", "saves", ["duplicate_of"], ["id"], ondelete="SET NULL")
    op.execute("UPDATE saves SET title_manual = 1 WHERE title <> ''")
    op.execute("UPDATE saves SET text_manual = 1 WHERE author_text <> ''")
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="prepare"))


def downgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("saves") as batch:
        batch.drop_constraint("fk_save_duplicate", type_="foreignkey")
        for name in ["source", "analysis", "manual_comments", "title_manual", "text_manual", "title_mode", "extraction_status", "ai_status", "extraction_error", "ai_error", "duplicate_of"]:
            batch.drop_column(name)
