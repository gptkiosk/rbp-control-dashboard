"""Standard job envelope on cards: kind, size, risk, area, route tier and the reason for the route."""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = depends_on = None

COLUMNS = (("assignee_user", 255), ("kind", 16), ("size", 4), ("risk", 8), ("area", 40), ("route_tier", 16), ("route_reason", 300))


def upgrade():
    with op.batch_alter_table("card") as batch:
        for name, length in COLUMNS:
            batch.add_column(sa.Column(name, sa.String(length=length), nullable=True))
    op.create_index("ix_card_kind", "card", ["kind"])
    op.create_index("ix_card_assignee_user", "card", ["assignee_user"])


def downgrade():
    op.drop_index("ix_card_assignee_user", table_name="card")
    op.drop_index("ix_card_kind", table_name="card")
    with op.batch_alter_table("card") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
