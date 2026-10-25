"""Cooperative workspace reservations enforced by task and chat dispatch."""
import sqlalchemy as sa
from alembic import op

revision = '0023'
down_revision = '0022'
branch_labels = depends_on = None


def upgrade():
    op.create_table('workspace_reservation',
        sa.Column('path', sa.String(1000), primary_key=True),
        sa.Column('id', sa.String(36), nullable=False, unique=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('started_at', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.Integer(), nullable=False))
    op.create_index('ix_workspace_reservation_project_id', 'workspace_reservation', ['project_id'])


def downgrade():
    op.drop_table('workspace_reservation')
