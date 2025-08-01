"""Deleted is_read fiels for feedback table

Revision ID: 5b1b0f1c447b
Revises: 83692652ffa5
Create Date: 2025-07-14 17:24:21.562514

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b1b0f1c447b'
down_revision = '83692652ffa5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.drop_column('is_read')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_read', sa.BOOLEAN(), autoincrement=False, nullable=False))

    # ### end Alembic commands ###
