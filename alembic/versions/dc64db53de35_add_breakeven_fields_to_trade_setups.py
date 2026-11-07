"""add_breakeven_fields_to_trade_setups

Revision ID: dc64db53de35
Revises: 3d6f1411b5a6
Create Date: 2026-11-07 13:41:01.700993

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc64db53de35'
down_revision: Union[str, None] = '3d6f1411b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trade_setups",
        sa.Column("active_stop_loss", sa.Numeric(precision=18, scale=4), nullable=True),
    )
    op.add_column(
        "trade_setups",
        sa.Column("breakeven_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("trade_setups", "breakeven_locked")
    op.drop_column("trade_setups", "active_stop_loss")
