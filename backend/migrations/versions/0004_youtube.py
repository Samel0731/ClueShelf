"""Account linkage and durable official synchronization."""
from alembic import op
import sqlalchemy as sa
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('youtube_connections', sa.Column('id', sa.String(), primary_key=True), sa.Column('owner_id', sa.String(), nullable=False, unique=True), sa.Column('channel_id', sa.String(), nullable=False), sa.Column('channel_title', sa.Text(), nullable=False), sa.Column('playlist_id', sa.String(), nullable=False), sa.Column('token_key', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('last_complete_scan_at', sa.Float()))
    op.create_table('youtube_oauth_states', sa.Column('digest', sa.String(), primary_key=True), sa.Column('browser_digest', sa.String(), nullable=False), sa.Column('verifier_key', sa.String(), nullable=False), sa.Column('expires_at', sa.Float(), nullable=False))
    op.create_table('youtube_syncs', sa.Column('id', sa.String(), primary_key=True), sa.Column('connection_id', sa.String(), sa.ForeignKey('youtube_connections.id'), nullable=False), sa.Column('token_key', sa.String(), nullable=False), sa.Column('state', sa.String(), nullable=False), sa.Column('cursor', sa.Text()), sa.Column('cursor_restarts', sa.Integer(), nullable=False, server_default='0'), *[sa.Column(name, sa.Integer(), nullable=False, server_default='0') for name in ('read_count','new_count','existing_count','skipped_count','failure_count','attempts')], sa.Column('skip_reasons', sa.JSON(), nullable=False), sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default='0'), sa.Column('lease_until', sa.Float()), sa.Column('lease_token', sa.String()), sa.Column('available_at', sa.Float(), nullable=False), sa.Column('error', sa.Text()), sa.Column('created_at', sa.Float(), nullable=False), sa.Column('updated_at', sa.Float(), nullable=False))
    op.create_index('youtube_sync_claim', 'youtube_syncs', ['state','available_at'])
    op.create_table('youtube_sources', sa.Column('connection_id', sa.String(), sa.ForeignKey('youtube_connections.id'), primary_key=True), sa.Column('video_id', sa.String(), primary_key=True), sa.Column('save_id', sa.String(), sa.ForeignKey('saves.id', ondelete='SET NULL')), sa.Column('first_seen_at', sa.Float(), nullable=False), sa.Column('last_seen_at', sa.Float(), nullable=False), sa.Column('sync_id', sa.String(), sa.ForeignKey('youtube_syncs.id'), nullable=False), sa.Column('source_status', sa.String(), nullable=False))


def downgrade():
    for name in ('youtube_sources','youtube_syncs','youtube_oauth_states','youtube_connections'):
        op.drop_table(name)
