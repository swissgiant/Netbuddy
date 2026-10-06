"""device.stack_name (logischer Switch-Stack, z.B. Meraki)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("device", sa.Column("stack_name", sa.String(length=255), nullable=True))
    op.create_index("ix_device_stack_name", "device", ["stack_name"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_device_stack_name", table_name="device")
    op.drop_column("device", "stack_name")
