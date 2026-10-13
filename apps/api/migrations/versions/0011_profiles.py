"""Private operator preferences, encrypted credentials and project delivery receipts."""
import sqlalchemy as sa
from alembic import op
revision = '0011'
down_revision = '0010'
branch_labels = depends_on = None

def upgrade():
    op.add_column('project',sa.Column('intake_key',sa.String(100)))
    op.create_index('ix_project_intake_key','project',['intake_key'],unique=True)
    op.create_table('user_profile',sa.Column('owner',sa.String(255),primary_key=True),sa.Column('preferences',sa.Text,nullable=False),sa.Column('discord_user_id',sa.String(22),unique=True),sa.Column('pair_hash',sa.String(64)),sa.Column('pair_expires',sa.Integer))
    op.create_table('user_credential',sa.Column('owner',sa.String(255),sa.ForeignKey('user_profile.owner'),primary_key=True),sa.Column('provider',sa.String(30),primary_key=True),sa.Column('ciphertext',sa.Text,nullable=False),sa.Column('hint',sa.String(4),nullable=False))
    op.create_table('project_delivery',sa.Column('id',sa.String(32),primary_key=True),sa.Column('source_key',sa.String(120),nullable=False,unique=True),sa.Column('project_id',sa.Integer,sa.ForeignKey('project.id'),nullable=False),sa.Column('revision',sa.Integer,nullable=False),sa.Column('owner',sa.String(255),nullable=False),sa.Column('destination',sa.String(80),nullable=False),sa.Column('message',sa.Text,nullable=False),sa.Column('images',sa.Text,nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('created_at',sa.Integer,nullable=False),sa.Column('message_id',sa.String(40)),sa.Column('error',sa.String(300)))
    op.create_index('ix_project_delivery_project_id','project_delivery',['project_id'])

def downgrade():
    op.drop_table('project_delivery');op.drop_table('user_credential');op.drop_table('user_profile')
    op.drop_index('ix_project_intake_key',table_name='project');op.drop_column('project','intake_key')
