"""Add locale to User model

Revision ID: 318b32e653fa
Revises: cf7b4bd32dfe
Create Date: 2025-07-14 17:00:52.918420

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '318b32e653fa'
down_revision = 'cf7b4bd32dfe'
branch_labels = None
depends_on = None


from alembic import op
import sqlalchemy as sa

def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('locale', sa.String(length=10), nullable=True))

    op.execute("UPDATE users SET locale = 'en' WHERE locale IS NULL")

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('locale', nullable=False)

def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('locale')
