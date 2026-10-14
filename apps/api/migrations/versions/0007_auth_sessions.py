"""Hash-only local browser sessions for Google sign-in and recovery."""
import sqlalchemy as sa
from alembic import op
revision = "0007"
down_revision = "0006"
branch_labels = depends_on = None


def upgrade():
    op.create_table("auth_session",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("origin", sa.String(300), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False))
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])


def downgrade():
    op.drop_table("auth_session")
