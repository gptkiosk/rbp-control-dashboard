"""Single-use task approval grants bound to a card, route pin, nonce and expiry.

Existing approvals carry no grant, so a standalone card that was approved but not yet run goes
back to Review at its next claim and needs one fresh approval. Project stories are unaffected.
"""
import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = depends_on = None


def upgrade():
    op.add_column('card', sa.Column('approval_grant', sa.Text))


def downgrade():
    with op.batch_alter_table('card') as batch:
        batch.drop_column('approval_grant')
