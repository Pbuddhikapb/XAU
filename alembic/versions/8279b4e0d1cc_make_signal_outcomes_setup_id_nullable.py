"""make_signal_outcomes_setup_id_nullable

Revision ID: 8279b4e0d1cc
Revises: dc64db53de35
Create Date: 2026-11-07 14:18:03.675201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8279b4e0d1cc'
down_revision: Union[str, None] = 'dc64db53de35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("signal_outcomes", "setup_id", nullable=True)


def downgrade() -> None:
    op.alter_column("signal_outcomes", "setup_id", nullable=False)
