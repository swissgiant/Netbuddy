"""reachable_ip (Cato-erreichbar) neben mgmt_ip (real) für physical_server + storage_device

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-10 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("physical_server", sa.Column("reachable_ip", postgresql.INET(), nullable=True))
    op.add_column("storage_device", sa.Column("reachable_ip", postgresql.INET(), nullable=True))


def downgrade() -> None:
    op.drop_column("storage_device", "reachable_ip")
    op.drop_column("physical_server", "reachable_ip")
