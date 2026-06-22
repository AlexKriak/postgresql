"""add_cities

Revision ID: 96c2d4ac64d3
Revises: 6a0e5b743f9d
Create Date: 2026-06-17 18:18:39.931323

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '96c2d4ac64d3'
down_revision: Union[str, Sequence[str], None] = '6a0e5b743f9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создание таблицы cities
    op.execute("CREATE TABLE IF NOT EXISTS catalog.cities (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);")
    op.execute("ALTER TABLE catalog.warehouses ADD COLUMN city_id INTEGER;")

    # Заполнение cities уникальными записями
    op.execute(
        "INSERT INTO catalog.cities (name)"
        "SELECT DISTINCT city FROM catalog.warehouses"
        "WHERE city IS NOT NULL"
        "ON CONFLICT (name) DO NOTHING;"
    )

    op.execute(
        "UPDATE catalog.warehouses"
        "SET city_id = c.id"
        "FROM catalog.cities c"
        "WHERE catalog.warehouses.city = c.name;"
    )

    op.execute(
        "ALTER TABLE catalog.warehouses"
        "ADD CONSTRAINT fk_warehouses_cities"
        "FOREIGN KEY (city_id) REFERENCES catalog.cities(id);"
    )

    op.execute("ALTER TABLE catalog.warehouses ALTER COLUMN city_id SET NOT NULL;")
    op.execute("ALTER TABLE catalog.warehouses DROP COLUMN city;")


def downgrade() -> None:
    op.execute("ALTER TABLE catalog.warehouses ADD COLUMN city TEXT;")
    op.execute(
        "UPDATE catalog.warehouses"
        "SET city = c.name"
        "FROM catalog.cities c"
        "WHERE catalog.warehouses.city_id = c.id;"
    )

    op.execute("ALTER TABLE catalog.warehouses ALTER COLUMN city SET NOT NULL;")
    op.execute("ALTER TABLE catalog.warehouses DROP CONSTRAINT fk_warehouses_cities;")
    op.execute("ALTER TABLE catalog.warehouses DROP COLUMN city_id;")
    op.execute("DROP TABLE IF EXISTS catalog.cities CASCADE;")
