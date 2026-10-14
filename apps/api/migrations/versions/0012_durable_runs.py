"""Durable run state: execution idempotency keys, attempts, supervisor identity, checkpoints.

`run.idempotency_key` is stable across an interruption requeue of the same execution;
`card.idempotency_key` carries it to the next claim. Partial unique indexes make the
exactly-once rules database constraints: one live attempt and one completion per key.
Pre-existing rows keep NULL keys and are not constrained.
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = depends_on = None


def upgrade():
    op.add_column('run', sa.Column('idempotency_key', sa.String(120)))
    op.add_column('run', sa.Column('attempt', sa.Integer, nullable=False, server_default='1'))
    op.add_column('run', sa.Column('requeued_from', sa.Integer))
    op.add_column('run', sa.Column('pid', sa.Integer))
    op.add_column('run', sa.Column('checkpoint', sa.Text))
    op.add_column('card', sa.Column('idempotency_key', sa.String(120)))
    op.create_index('ix_run_idempotency_key', 'run', ['idempotency_key'])
    op.create_index('ux_run_key_live', 'run', ['idempotency_key'], unique=True,
                    sqlite_where=sa.text("idempotency_key IS NOT NULL AND stage = 'running'"))
    op.create_index('ux_run_key_done', 'run', ['idempotency_key'], unique=True,
                    sqlite_where=sa.text("idempotency_key IS NOT NULL AND stage IN ('succeeded', 'awaiting_approval')"))


def downgrade():
    op.drop_index('ux_run_key_done', table_name='run')
    op.drop_index('ux_run_key_live', table_name='run')
    op.drop_index('ix_run_idempotency_key', table_name='run')
    with op.batch_alter_table('card') as batch:
        batch.drop_column('idempotency_key')
    with op.batch_alter_table('run') as batch:
        for name in ('checkpoint', 'pid', 'requeued_from', 'attempt', 'idempotency_key'):
            batch.drop_column(name)
