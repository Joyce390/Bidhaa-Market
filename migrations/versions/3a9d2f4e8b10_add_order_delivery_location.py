"""Add delivery location (map pin) and notes to orders

Revision ID: 3a9d2f4e8b10
Revises: 7b6c14667da9
Create Date: 2026-09-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a9d2f4e8b10'
down_revision = '7b6c14667da9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('delivery_notes', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('delivery_lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('delivery_lng', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_column('delivery_lng')
        batch_op.drop_column('delivery_lat')
        batch_op.drop_column('delivery_notes')
