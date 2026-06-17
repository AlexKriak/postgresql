"""create_roles

Revision ID: 846a32c3bb81_create_roles
Revises: e3c29b621792
Create Date: 2026-06-17 00:32:48.036177

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '846a32c3bb81_create_roles'
down_revision: Union[str, Sequence[str], None] = '6a0e5b743f9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
     # Создание ролей inventory_manager и worker
     op.execute(sa.text("CREATE ROLE inventory_manager LOGIN PASSWORD 'secure_password_inventory';"))
     op.execute(sa.text("CREATE ROLE worker LOGIN PASSWORD 'secure_password_worker';"))

     op.drop_constraint('auth_users_role_check', 'users', schema='auth')
     op.create_check_constraint(
         constraint_name='auth_users_role_check',
         table_name='users',
         condition="role IN ('catalog_manager', 'sales_manager', 'inventory_manager', 'worker')",
         schema='auth'
     )


def downgrade() -> None:
    op.execute(sa.text("DROP ROLE IF EXISTS worker;"))
    op.execute(sa.text("DROP ROLE IF EXISTS inventory_manager;"))

    op.drop_constraint('auth_users_role_check', 'users', schema='auth')
    op.create_check_constraint(
        constraint_name='auth_users_role_check',
        table_name='users',
        condition="role IN ('catalog_manager', 'sales_manager')",
        schema='auth'
    )
