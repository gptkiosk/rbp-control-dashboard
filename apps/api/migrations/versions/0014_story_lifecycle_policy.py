"""Per-story timeout, retry and retry scheduling policy."""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = depends_on = None

def upgrade():
    op.add_column('card', sa.Column('idle_timeout_s', sa.Integer()))
    op.add_column('card', sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('card', sa.Column('retry_backoff_s', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('card', sa.Column('retry_after', sa.Integer()))
    op.create_index('ix_card_retry_after', 'card', ['retry_after'])

def downgrade():
    op.drop_index('ix_card_retry_after', table_name='card')
    with op.batch_alter_table('card') as batch:
        for name in ('retry_after', 'retry_backoff_s', 'max_attempts', 'idle_timeout_s'):
            batch.drop_column(name)
