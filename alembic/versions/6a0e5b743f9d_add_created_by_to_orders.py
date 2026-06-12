"""permissions_to_roles

Revision ID: 6a0e5b743f9d
Revises: 
Create Date: 2026-06-11 22:20:56.926583

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6a0e5b743f9d'
down_revision: Union[str, Sequence[str], None] = 'b9f36182cdce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('created_by', sa.Integer(), nullable=True), schema='sales')
    op.execute("UPDATE sales.orders SET created_by = (SELECT id FROM auth.users WHERE id = 1 LIMIT 1) WHERE created_by IS NULL;")

    op.create_foreign_key(
        constraint_name='fk_orders_users_created_by',
        source_table='orders',
        referent_table='users',
        local_cols=['created_by'],
        remote_cols=['id'],
        source_schema='sales',
        referent_schema='auth'
    )

    op.alter_column('orders', 'created_by', nullable=False, schema='sales')


def downgrade() -> None:
    op.drop_constraint('fk_orders_users_created_by', 'orders', schema='sales')
    op.drop_column('orders', 'created_by', schema='sales')
