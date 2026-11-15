"""Search chunks, literal trigram search, and independent manual classification."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("saves") as batch:
        batch.add_column(sa.Column("manual_topics", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("manual_tags", sa.JSON(), nullable=True))
    op.create_table("search_chunks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("save_id", sa.String(), sa.ForeignKey("saves.id", ondelete="CASCADE"), nullable=False), sa.Column("field", sa.String(), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("normalized_text", sa.Text(), nullable=False), sa.Column("fingerprint", sa.String(), nullable=False), sa.Column("embedding", sa.JSON(), nullable=True), sa.Column("embedding_model", sa.String(), nullable=True), sa.Column("embedding_attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("embedding_error", sa.Text(), nullable=True))
    op.create_index("ix_search_chunks_save_id", "search_chunks", ["save_id"])
    op.execute("CREATE VIRTUAL TABLE search_fts USING fts5(chunk_id UNINDEXED, text, tokenize='trigram')")
    op.execute("CREATE TRIGGER search_insert AFTER INSERT ON search_chunks BEGIN INSERT INTO search_fts(rowid,chunk_id,text) VALUES(new.id,new.id,new.normalized_text); END")
    op.execute("CREATE TRIGGER search_update AFTER UPDATE OF normalized_text ON search_chunks BEGIN DELETE FROM search_fts WHERE rowid=old.id; INSERT INTO search_fts(rowid,chunk_id,text) VALUES(new.id,new.id,new.normalized_text); END")
    op.execute("CREATE TRIGGER search_delete AFTER DELETE ON search_chunks BEGIN DELETE FROM search_fts WHERE rowid=old.id; END")


def downgrade():
    for trigger in ("search_insert", "search_update", "search_delete"):
        op.execute(f"DROP TRIGGER {trigger}")
    op.execute("DROP TABLE search_fts")
    op.drop_table("search_chunks")
    with op.batch_alter_table("saves") as batch:
        batch.drop_column("manual_topics")
        batch.drop_column("manual_tags")
