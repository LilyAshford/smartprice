"""Add unique constraint on user_id and url for products

Revision ID: e4d4ae4c2a0f
Revises: 4614c07e1cb5
Create Date: 2025-07-06 10:08:16.249651

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4d4ae4c2a0f'
down_revision = '4614c07e1cb5'
branch_labels = None
depends_on = None



from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        if op.get_bind().execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'products' AND indexname = 'ix_product_url'")).fetchone():
            batch_op.drop_index('ix_product_url')
        if not op.get_bind().execute(
                text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_name = 'products' AND constraint_name = 'uq_user_product_url'")).fetchone():
            batch_op.create_unique_constraint('uq_user_product_url', ['user_id', 'url'])

def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        if op.get_bind().execute(
                text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_name = 'products' AND constraint_name = 'uq_user_product_url'")).fetchone():
            batch_op.drop_constraint('uq_user_product_url', type_='unique')
        if not op.get_bind().execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'products' AND indexname = 'ix_product_url'")).fetchone():
            batch_op.create_index('ix_product_url', ['url'], unique=False)

    # ### end Alembic commands ###
