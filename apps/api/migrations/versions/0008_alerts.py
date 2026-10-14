"""Durable alert outbox and observation baseline."""
import sqlalchemy as sa
from alembic import op
revision = "0008"
down_revision = "0007"
branch_labels = depends_on = None

def upgrade():
    op.create_table("alert_event", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_key", sa.String(200), nullable=False, unique=True),
        sa.Column("run_id", sa.Integer), sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False), sa.Column("destination", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("sent_at", sa.Integer), sa.Column("message_id", sa.String(40)), sa.Column("reviewed_at", sa.Integer), sa.Column("error", sa.String(300)))
    op.create_index("ix_alert_event_run_id", "alert_event", ["run_id"])
    op.create_index("ix_alert_event_status", "alert_event", ["status"])
    op.create_table("alert_state", sa.Column("key", sa.String(80), primary_key=True), sa.Column("value", sa.Text, nullable=False))

def downgrade():
    op.drop_table("alert_event")
    op.drop_table("alert_state")
