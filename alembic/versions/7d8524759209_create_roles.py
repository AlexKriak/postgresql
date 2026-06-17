"""create_roles

Revision ID: 7d8524759209
Revises: e5ffcaf99690
Create Date: 2026-06-17 18:46:29.197222

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d8524759209'
down_revision: Union[str, Sequence[str], None] = 'e5ffcaf99690'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создание ролей inventory_manager и worker отдельными запросам из txt файла
    op.execute("ALTER TABLE auth.users DROP CONSTRAINT IF EXIST auth_users_role_check;")
    op.execute(
        "ALTER TABLE auth.users"
        "ADD CONSTRAINT auth_users_role_check"
        "CHECK (role IN ('catalog_manager', 'sales_manager', 'inventory_manager', 'worker'));"
    )

    # Выдача прав для новых ролей
    op.execute("GRANT USAGE ON SCHEMA inventory TO inventory_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory TO inventory_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory TO inventory_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON TABLES TO inventory_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON SEQUENCES TO inventory_manager;")

    op.execute("GRANT USAGE ON SCHEMA sales TO inventory_manager;")
    op.execute("GRANT SELECT ON SCHEMA sales TO inventory_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT SELECT ON TABLES TO inventory_manager;")
    op.execute("GRANT UPDATE (status) ON sales.orders TO inventory_manager;")

    op.execute("GRANT ALL PRIVILEGES ON inventory.stock TO worker;")
    op.execute("GRANT UPDATE ON inventory.reserves TO worker;")

    # Обновление статусов
    op.execute("GRANT UPDATE (status, shipped_at) ON inventory.delivery_items TO worker;")
    op.execute("GRANT UPDATE (status, started_at, arriving_at) ON inventory.transfer TO worker;")
    op.execute("GRANT UPDATE (status, shipped_at) ON inventory.transfer_items TO worker;")
    op.execute("GRANT UPDATE (received_at) ON inventory.transfer TO worker;")
    op.execute("GRANT UPDATE (received_at) ON inventory.transfer_items TO worker;")

    op.execute("GRANT USAGE ON SCHEMA inventory TO worker;")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO worker;")


def downgrade() -> None:
    op.execute("ALTER TABLE auth.users DROP CONSTRAINT IF EXIST auth_users_role_check;")
    op.execute(
        "ALTER TABLE auth.users"
        "ADD CONSTRAINT auth_users_role_check"
        "CHECK (role IN ('catalog_manager', 'sales_manager'));"
    )

    op.execute("REVOKE UPDATE (status) ON sales.orders FROM inventory_manager;")
    op.execute("ALTER TABLE DEFAULT PRIVILEGES ON SCHEMA sales REVOKE SELECT ON TABLE FROM inventory_manager;")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA sales FROM inventory_manager")
    op.execute("REVOKE USAGES ON SCHEMA sales FROM inventory_manager FROM inventory_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA inventory REVOKE ALL ON SEQUENCES FROM inventory_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA inventory REVOKE ALL ON TABLES FROM inventory_manager;")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory FROM inventory_manager;")
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory FROM inventory_manager;")
    op.execute("REVOKE USAGES ON SCHEMA FROM inventory_manager;")

    op.execute("REVOKE UPDATE (received_at) ON inventory.transfer FROM worker;")
    op.execute("REVOKE UPDATE (received_at) ON inventory.transfer_item FROM worker;")
    op.execute("REVOKE UPDATE (status, started_at, arriving_at) ON inventory.transfer FROM worker;")
    op.execute("REVOKE UPDATE (status, shipped_at) ON inventory.delivery_items FROM worker;")
    op.execute("REVOKE UPDATE (status, shipped_at) ON inventory.transfer_items FROM worker;")
    op.execute("REVOKE UPDATE ON inventory.reserves FROM worker;")
    op.execute("REVOKE ALL PRIVILEGES ON inventory.stock FROM worker;")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA inventory FROM worker;")
    op.execute("REVOKE USAGES ON SCHEMA inventory FROM worker;")

