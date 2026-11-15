"""Independent IO/AI/index lanes and persistent weighted AI scheduling."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("size_class", sa.String(), nullable=False, server_default="small"))
    op.create_table("queue_schedule", sa.Column("name", sa.String(), primary_key=True), sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    # Existing pending AI work has not yet been sized. Use the same bounded
    # source fields, without importing changing application model definitions.
    connection = op.get_bind()
    import json
    rows = connection.execute(sa.text("SELECT j.id,s.platform,s.title,s.author_text,s.source,s.manual_comments FROM jobs j JOIN saves s ON s.id=j.save_id WHERE j.state='queued' AND j.kind='analyze'"))
    for job_id, platform, title, body, raw_source, manual in rows:
        source = (json.loads(raw_source) if isinstance(raw_source, str) else raw_source) or {}
        comments = source.get("comments", []) if platform == "threads" else []
        if platform == "threads" and manual:
            comments = [{"text": manual}, *comments]
        length = len(source.get("original_title", title)[:300]) + len(body[:2500]) + sum(len(item["text"][:100]) for item in comments[:11])
        size = "small" if length <= 1000 else "medium" if length <= 3000 else "large"
        connection.execute(sa.text("UPDATE jobs SET size_class=:size WHERE id=:id"), {"size": size, "id": job_id})


def downgrade():
    op.drop_table("queue_schedule")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("size_class")
