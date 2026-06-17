"""add_cities

Revision ID: e3c29b621792_add_cities
Revises: 6a0e5b743f9d
Create Date: 2026-06-16 23:52:16.319705

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3c29b621792_add_cities'
down_revision: Union[str, Sequence[str], None] = '6a0e5b743f9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создание таблицы catalog.cities
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS catalog.cities (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);"))
    op.add_column('warehouses', sa.Column('city_id', sa.Integer(), nullable=True), schema='catalog')

    # Заполнение catalog.cities уникальными записями
    insert_cities_query = sa.text("""
        INSERT INTO catalog.cities (name)
        SELECT DISTINCT city FROM catalog.warehouses
        WHERE city IS NOT NULL
        ON CONFLICT (name) DO NOTHING;
    """)
    op.execute(insert_cities_query)

    update_warehouse_city_id_query = sa.text("""
        UPDATE catalog.warehouses
        SET city_id = c.id
        FROM catalog.cities c
        WHERE catalog.warehouses.city = c.name;
    """)
    op.execute(update_warehouse_city_id_query)

    op.create_foreign_key(
        constraint_name='fk_warehouses_cities',
        source_table='warehouses',
        referent_table='cities',
        local_cols=['city_id'],
        remote_cols=['id'],
        source_schema='catalog',
        referent_schema='catalog'
    )

    op.alter_column('warehouses', 'city_id', nullable=False, schema='catalog')
    op.drop_column('warehouses', 'city', schema='catalog')


def downgrade() -> None:
    op.add_column('warehouses', sa.Column('city', sa.Text(), nullable=True), schema='catalog')
    fill_old_city_column_query = sa.text("""
        UPDATE catalog.warehouses
        SET city = c.name
        FROM catalog.cities c
        WHERE catalog.warehouses.city_id = c.id;
    """)
    op.execute(fill_old_city_column_query)

    op.alter_column('warehouses', 'city', nullable=False, schema='catalog')
    op.drop_constraint('fk_warehouses_cities', 'warehouses', schema='catalog')

    op.drop_column('warehouses', 'city_id', schema='catalog')
    op.execute(sa.text("DROP TABLE IF EXISTS catalog.cities CASCADE;"))
