"""initial_tables

Revision ID: 371567bdcab3
Revises: 
Create Date: 2026-06-08 20:24:39.195305

"""
from typing import Sequence, Union
from enum import Enum
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '371567bdcab3'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создание схемы catalog и sales, если не существует
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog;")
    op.execute("CREATE SCHEMA IF NOT EXISTS sales;")

    # Создание таблицы product_categories
    op.execute(
        "CREATE TABLE catalog.product_categories (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE)"
    )

    # Создание таблицы warehouses
    op.execute(
        "CREATE TABLE catalog.warehouses ("
        "id SERIAL PRIMARY KEY, "
        "city VARCHAR(255) NOT NULL, "
        "address TEXT NOT NULL, "
        "label TEXT, "
        "is_central BOOLEAN NOT NULL DEFAULT FALSE"
        ")"
    )

    # Создание таблицы products
    op.execute(
        "CREATE TABLE catalog.products ("
        "id SERIAL PRIMARY KEY, "
        "sku VARCHAR(30) NOT NULL UNIQUE, "
        "name VARCHAR(255) NOT NULL, "
        "price NUMERIC(10, 2) NOT NULL, "
        "category_id INTEGER NOT NULL,"
        "FOREIGN KEY (category_id) REFERENCES catalog.product_categories(id)"
        ")"
    )

    # Создание таблицы stock
    op.execute(
        "CREATE TABLE catalog.stock ("
        "id SERIAL PRIMARY KEY, "
        "products_id INTEGER NOT NULL,"
        "warehouses_id INTEGER NOT NULL,"
        "FOREIGN KEY (products_id) REFERENCES catalog.products(id),"
        "FOREIGN KEY (warehouses_id) REFERENCES catalog.warehouses(id)"
        ")"
    )

    op.execute(
        "CREATE TYPE sales.order_status AS ENUM "
        "("
        "'unpublished', "
        "'new', "
        "'processing', "
        "'pending', "
        "'packing', "
        "'shipped'"
        ")"
    )

    # Создание таблицы orders
    op.execute(
        "CREATE TABLE sales.orders ("
        "id SERIAL PRIMARY KEY, "
        "status sales.order_status NOT NULL DEFAULT 'unpublished',"
        "total_amount NUMERIC(12,2) NOT NULL,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "warehouses_id INTEGER NOT NULL,"
        "FOREIGN KEY (warehouses_id) REFERENCES catalog.warehouses(id)"
        ")"
    )

    # Создание таблицы order_items
    op.execute(
        "CREATE TABLE sales.order_items ("
        "id SERIAL PRIMARY KEY, "
        "product_id INTEGER NOT NULL, "
        "price NUMERIC(10,2) NOT NULL, "
        "quantity INTEGER NOT NULL, "
        "orders_id INTEGER NOT NULL, "
        "FOREIGN KEY (product_id) REFERENCES catalog.products(id), "
        "FOREIGN KEY (orders_id) REFERENCES sales.orders(id)"
        ")"
    )
    pass


def downgrade() -> None:
    # Удаление таблиц
    op.execute("DROP TABLE IF EXIST sales.orders_item")
    op.execute("DROP TABLE IF EXIST sales.orders")
    op.execute("DROP TABLE IF EXIST catalog.stock")
    op.execute("DROP TABLE IF EXIST catalog.products")
    op.execute("DROP TABLE IF EXIST catalog.warehouses")
    op.execute("DROP TABLE IF EXIST catalog.product_categories")

    op.execute("DROP TYPE IF EXIST sales.order_status")

    # Удаление схем
    op.execute("DROP SCHEMA IF EXISTS catalog CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS sales CASCADE;")
    pass
