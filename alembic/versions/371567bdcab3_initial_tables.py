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
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS catalog;"))
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS sales;"))

    # Создание таблицы product_categories
    op.create_table(
        'product_categories',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=255), nullable=False, unique=True),
        schema='catalog'
    )

    # Создание таблицы warehouses
    op.create_table(
        'warehouses',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('city', sa.String(length=255), nullable=False),
        sa.Column('address', sa.Text, nullable=False),
        sa.Column('label', sa.Text, nullable=True),
        sa.Column('is_central', sa.Boolean, nullable=False, default=False),
        schema='catalog'
    )

    # Создание таблицы products
    op.create_table(
        'products',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku', sa.String(length=30), nullable=False, unique=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('category_id', sa.Integer, sa.ForeignKey('catalog.product_categories.id'), nullable=False),
        schema='catalog'
    )

    # Создание таблицы stock
    op.create_table(
        'stock',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('products_id', sa.Integer, sa.ForeignKey('catalog.products.id'), nullable=False),
        sa.Column('warehouses_id', sa.Integer, sa.ForeignKey('catalog.warehouses.id'), nullable=False),
    )

    statuses_enum = sa.Enum(
        'unpublished',
        'new',
        'processing',
        'pending',
        'packing',
        'shipped',
    )

    # Создание таблицы orders
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('status', statuses_enum, nullable=False, default='unpublished'),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.Time(timezone=True), nullable=False),
        sa.Column('warehouses_id', sa.Integer, sa.ForeignKey('catalog.warehouses.id'), nullable=False),
        schema='sales'
    )
    pass


def downgrade() -> None:
    # Удаление таблиц
    op.drop_table('products', schema='catalog')
    op.drop_table('orders', schema='sales')

    # Удаление таблиц
    op.drop_table('stock', schema='sales')
    op.drop_table('warehouses', schema='catalog')
    op.drop_table('product_categories', schema='catalog')
    op.drop_table('order_item', schema='sales')

    # Удаление схем
    op.execute(sa.text("DROP SCHEMA IF EXISTS catalog CASCADE;"))
    op.execute(sa.text("DROP SCHEMA IF EXISTS sales CASCADE;"))
    pass
