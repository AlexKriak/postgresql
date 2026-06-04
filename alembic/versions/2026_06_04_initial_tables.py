# alembic/versions/001_initial_tables.py
"""Initial tables

Revision ID: 001
Revises:
Create Date: 2026-06-04 12:56:27.160782

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создание схемы catalog, если не существует
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS catalog;"))

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

    # Добавление ограничения: только один центральный склад
    op.execute(sa.text("""
        ALTER TABLE catalog.warehouses ADD CONSTRAINT one_central_only CHECK (
            (SELECT COUNT(*) FROM catalog.warehouses WHERE is_central = true) <= 1
        );
    """))

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


def downgrade() -> None:
    # Удаление таблицы products
    op.drop_table('products', schema='catalog')

    # Удаление ограничения перед удалением таблицы warehouses
    op.execute(sa.text("ALTER TABLE catalog.warehouses DROP CONSTRAINT IF EXISTS one_central_only;"))

    # Удаление таблицы warehouses
    op.drop_table('warehouses', schema='catalog')

    # Удаление таблицы product_categories
    op.drop_table('product_categories', schema='catalog')

    # Удаление схемы catalog
    op.execute(sa.text("DROP SCHEMA IF EXISTS catalog CASCADE;"))
