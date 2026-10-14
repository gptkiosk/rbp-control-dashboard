"""Expiring, revocable agent capabilities, distinct from browser sessions."""
import sqlalchemy as sa
from alembic import op
revision = "0009"
down_revision = "0008"
branch_labels = depends_on = None

def upgrade():
    op.create_table("agent_access", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("agent", sa.String(40), nullable=False), sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False), sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False), sa.Column("revoked_at", sa.Integer),
        sa.Column("last_used_at", sa.Integer))

def downgrade():
    op.drop_table("agent_access")
