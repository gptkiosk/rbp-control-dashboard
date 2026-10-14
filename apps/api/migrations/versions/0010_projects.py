"""Versioned planning maps, task bindings and append-only shared project memory."""
import sqlalchemy as sa
from alembic import op
revision = "0010"
down_revision = "0009"
branch_labels = depends_on = None

def upgrade():
    op.create_table('project', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('document', sa.Text, nullable=False), sa.Column('revision', sa.Integer, nullable=False),
        sa.Column('state', sa.String(30), nullable=False), sa.Column('approved_manifest', sa.Text),
        sa.Column('pipeline', sa.Text), sa.Column('error', sa.Text),
        sa.Column('created_by', sa.String(255), nullable=False), sa.Column('created_at', sa.Integer, nullable=False),
        sa.Column('updated_at', sa.Integer, nullable=False))
    op.create_table('project_task', sa.Column('card_id', sa.Integer, sa.ForeignKey('card.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('project.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('revision', sa.Integer, nullable=False), sa.Column('node_key', sa.String(80), nullable=False),
        sa.Column('role', sa.String(30), nullable=False))
    op.create_index('ix_project_task_project_id', 'project_task', ['project_id'])
    op.create_table('project_memory', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('project.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False), sa.Column('text', sa.Text, nullable=False),
        sa.Column('actor', sa.String(255), nullable=False), sa.Column('card_id', sa.Integer),
        sa.Column('run_id', sa.Integer), sa.Column('created_at', sa.Integer, nullable=False))
    op.create_index('ix_project_memory_project_id', 'project_memory', ['project_id'])

def downgrade():
    op.drop_table('project_memory'); op.drop_table('project_task'); op.drop_table('project')
