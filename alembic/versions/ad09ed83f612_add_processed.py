"""add_processed

Revision ID: ad09ed83f612
Revises: 7d8524759209
Create Date: 2026-06-18 23:04:17.463801

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad09ed83f612'
down_revision: Union[str, Sequence[str], None] = '7d8524759209'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales.orders ADD COLUMN processed_by INTEGER;")-
    op.execute(
        "ALTER TABLE sales.orders"
        "ADD CONSTRAINT fk_orders_users_processed_by"
        "FOREIGN KEY (processed_by) REFERENCES auth.users(id);"
    )
    op.execute("ALTER TABLE sales.orders ALTER COLUMN processed_by SET NOT NULL;")


def downgrade() -> None:
    op.execute("ALTER TABLE sales.orders DROP CONSTRAINT IF EXISTS fk_orders_users_processed_by;")
    op.execute("ALTER TABLE sales.orders DROP COLUMN processed_by;")
