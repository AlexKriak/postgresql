"""create_worker_sales_view

Revision ID: 001_create_worker_sales_view
Revises: e5ffcaf99690
Create Date: 2026-07-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_create_worker_sales_view'
down_revision: Union[str, Sequence[str], None] = 'e5ffcaf99690'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE OR REPLACE VIEW inventory.worker_sales_view AS
        SELECT
            o.id AS order_id,
            o.status AS order_status,
            o.warehouses_id AS target_warehouse_id
        FROM sales.orders o;
    """))

    op.execute("GRANT SELECT ON inventory.worker_sales_view TO worker;")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON inventory.worker_sales_view FROM worker;")

    op.execute("DROP VIEW IF EXISTS inventory.worker_sales_view;")