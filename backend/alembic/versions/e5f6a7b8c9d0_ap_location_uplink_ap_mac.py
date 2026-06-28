"""ap_location.uplink_ap_mac (Eltern-AP für Mesh-Kante)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "ap_location", sa.Column("uplink_ap_mac", sa.String(length=12), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ap_location", "uplink_ap_mac")
