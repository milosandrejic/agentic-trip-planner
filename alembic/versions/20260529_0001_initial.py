"""initial empty migration

Revision ID: 20260529_0001
Revises:
Create Date: 2026-05-29

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "20260529_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
