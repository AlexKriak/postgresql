"""add_tables_inventory

Revision ID: e5ffcaf99690
Revises: 96c2d4ac64d3
Create Date: 2026-06-17 18:20:40.712857

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5ffcaf99690'
down_revision: Union[str, Sequence[str], None] = '96c2d4ac64d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS inventory;"))

    # Создание таблицы inventory.deliveries
    op.execute(
        "CREATE TABLE inventory.deliveries ("
        "order_id INTEGER PRIMARY KEY,"
        "status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipping', 'shipped')),"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "shipped_at TIMESTAMPTZ,"
        "FOREIGN KEY (order_id) REFERENCES sales.orders(id)"
        ");"
    )

    # Создание таблицы inventory.routes
    op.execute(
        "CREATE TABLE inventory.routes ("
        "from_city_id INTEGER NOT NULL,"
        "to_city_id INTEGER NOT NULL,"
        "duration INTERVAL NOT NULL,"
        "total_threshold NUMERIC(12, 2) NOT NULL DEFAULT 0,"
        "PRIMARY KEY (from_city_id, to_city_id),"
        "FOREIGN KEY (from_city_id) REFERENCES catalog.cities(id),"
        "FOREIGN KEY (to_city_id) REFERENCES catalog.cities(id)"
        ");"
    )

    # Создание таблицы stock
    op.execute(
        "CREATE TABLE inventory.stock ("
        "warehouse_id INTEGER NOT NULL,"
        "product_id INTEGER NOT NULL,"
        "quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),"
        "FOREIGN KEY (warehouse_id) REFERENCES catalog.warehouses(id),"
        "FOREIGN KEY (product_id) REFERENCES catalog.products(id),"
        "PRIMARY KEY(warehouse_id, product_id)"
        ");"
    )

    # Создание таблицы reserves
    op.execute(
        "CREATE TABLE inventory.reserves ("
        "id SERIAL PRIMARY KEY,"
        "order_id INTEGER,"
        "product_id INTEGER NOT NULL,"
        "quantity INTEGER NOT NULL CHECK (quantity > 0),"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "FOREIGN KEY (order_id) REFERENCES sales.orders(id),"
        "FOREIGN KEY (product_id) REFERENCES catalog.products(id),"
        ");"
    )

    # Создание таблицы delivery_items
    op.execute(
        "CREATE TABLE inventory.delivery_items ("
        "order_id INTEGER NOT NULL,"
        "product_id INTEGER NOT NULL,"
        "quantity INTEGER NOT NULL CHECK (quantity > 0),"
        "status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipped')),"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "shipped_at TIMESTAMPTZ,"
        "FOREIGN KEY (order_id) REFERENCES sales.orders(id),"
        "FOREIGN KEY (product_id) REFERENCES catalog.products(id),"
        "PRIMARY KEY(order_id, product_id)"
        ");"
    )

    # Создание таблицы transfers
    op.execute(
        "CREATE TABLE inventory.transfers ("
        "id SERIAL PRIMARY KEY,"
        "from_warehouse_id INTEGER NOT NULL,"
        "to_warehouse_id INTEGER NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'planned' "
        "CHECK (status IN ('planned', 'shipping', 'in_transit', 'arrived', 'received')),"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "started_at TIMESTAMPTZ,"
        "arriving_at TIMESTAMPTZ,"
        "received_at TIMESTAMPTZ,"
        "FOREIGN KEY (from_warehouse_id) REFERENCES catalog.warehouses(id),"
        "FOREIGN KEY (to_warehouse_id) REFERENCES catalog.warehouses(id)"
        ");"
    )

    # Создание таблицы transfer_items
    op.execute(
        "CREATE TABLE inventory.transfer_items ("
        "id SERIAL PRIMARY KEY,"
        "transfer_id INTEGER NOT NULL,"
        "product_id INTEGER NOT NULL,"
        "quantity INTEGER NOT NULL CHECK (quantity > 0),"
        "requested_by INTEGER,"
        "reserve_id INTEGER,"
        "status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'shipped', 'received')),"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "shipped_at TIMESTAMPTZ,"
        "received_at TIMESTAMPTZ,"
        "FOREIGN KEY (transfer_id) REFERENCES inventory.transfers(id),"
        "FOREIGN KEY (product_id) REFERENCES catalog.products(id),"
        "FOREIGN KEY (requested_by) REFERENCES auth.users(id),"
        "FOREIGN KEY (reserve_id) REFERENCES inventory.reserves(id)"
        ");"
    )

    # Индексы
    op.create_index('ix_delivery_items_order_id', 'delivery_items', ['order_id'], schema='inventory')
    op.create_index('ix_delivery_items_status', 'delivery_items', ['status'], schema='inventory')
    op.create_index('ix_transfer_items_transfer_id', 'transfer_items', ['transfer_id'], schema='inventory')
    op.create_index('ix_transfer_items_status', 'transfer_items', ['status'], schema='inventory')
    op.create_index('ix_reserves_order_id', 'reserves', ['order_id'], schema='inventory')
    op.create_index('ix_stock_warehouse_product', 'stock', ['warehouse_id', 'product_id'], schema='inventory')


def downgrade() -> None:
    op.drop_index('ix_transfer_items_status', schema='inventory')
    op.drop_index('ix_transfer_items_transfer_id', schema='inventory')
    op.drop_index('ix_reserves_order_id', schema='inventory')
    op.drop_index('ix_stock_warehouse_product', schema='inventory')
    op.drop_index('ix_delivery_items_status', schema='inventory')
    op.drop_index('ix_delivery_items_order_id', schema='inventory')

    op.execute("DROP TABLE IF EXISTS inventory.transfer_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.transfers CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.delivery_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.deliveries CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.reserves CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.stock CASCADE;")
    op.execute("DROP TABLE IF EXISTS inventory.routes CASCADE;")

    op.execute(sa.text("DROP SCHEMA IF EXISTS inventory CASCADE;"))
