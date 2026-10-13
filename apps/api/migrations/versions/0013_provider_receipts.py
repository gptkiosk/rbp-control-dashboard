"""Deduplicate provider responses across retry attempts, not just within one run."""
import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = depends_on = None


def upgrade():
    op.create_table('provider_receipt',
        sa.Column('provider', sa.String(80), primary_key=True),
        sa.Column('response_id', sa.String(300), primary_key=True),
        sa.Column('run_id', sa.Integer, sa.ForeignKey('run.id', ondelete='SET NULL')),
        sa.Column('payload', sa.Text, nullable=False))


def downgrade():
    op.drop_table('provider_receipt')
