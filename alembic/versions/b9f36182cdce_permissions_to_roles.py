"""permissions_to_roles

Revision ID: b9f36182cdce
Revises: 
Create Date: 2026-06-11 21:46:01.048262

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b9f36182cdce'
down_revision: Union[str, Sequence[str], None] = '371567bdcab3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Выдача прав catalog_manager на схему catalog и на будущие таблицы
    op.execute("GRANT USAGE ON SCHEMA catalog TO catalog_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog TO catalog_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog TO catalog_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON TABLES TO catalog_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON SEQUENCES TO catalog_manager;")

    # Выдача прав sales_manager на схему sales и на будущие таблицы
    op.execute("GRANT USAGE ON SCHEMA sales TO sales_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA sales TO sales_manager;")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA sales TO sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT ALL ON TABLES TO sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT ALL ON SEQUENCES TO sales_manager;")

    # Выдача прав sales_manager на чтение схемы catalog и на будущие таблицы
    op.execute("GRANT USAGE ON SCHEMA catalog TO sales_manager;")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT SELECT ON TABLES TO sales_manager;")

    # Выдача прав catalog_manager и sales_manager на схему auth (чтение) и на будущие таблицы
    op.execute("GRANT USAGE ON SCHEMA auth TO catalog_manager, sales_manager;")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA auth TO catalog_manager, sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT SELECT ON TABLES TO catalog_manager, sales_manager;")


def downgrade() -> None:
    # Отзыв прав
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog REVOKE ALL ON TABLES FROM catalog_manager, sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog REVOKE ALL ON TABLES FROM sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA catalog REVOKE ALL ON SEQUENCES FROM catalog_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA sales REVOKE ALL ON TABLES FROM sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA sales REVOKE ALL ON SEQUENCES FROM sales_manager;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA auth REVOKE SELECT ON TABLES FROM catalog_manager, sales_manager;")

    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog FROM catalog_manager;")
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog FROM catalog_manager;")
    op.execute("REVOKE USAGE ON SCHEMA catalog FROM catalog_manager;")

    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA sales FROM sales_manager;")
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA sales FROM sales_manager;")
    op.execute("REVOKE USAGE ON SCHEMA sales FROM sales_manager;")

    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA catalog FROM sales_manager;")
    op.execute("REVOKE USAGE ON SCHEMA catalog FROM sales_manager;")

    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM catalog_manager, sales_manager;")
    op.execute("REVOKE USAGE ON SCHEMA auth FROM catalog_manager, sales_manager;")
