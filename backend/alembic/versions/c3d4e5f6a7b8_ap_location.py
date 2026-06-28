"""AP location (sticky UniFi-AP ↔ switch/port map)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-28 09:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ap_location",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("ap_mac", sa.String(length=12), nullable=False),
        sa.Column("ap_name", sa.String(length=128), server_default="", nullable=False),
        sa.Column("ap_model", sa.String(length=64), nullable=True),
        sa.Column("ap_ip", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="unknown", nullable=False),
        sa.Column("device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("port", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("mesh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("located_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ap_location_ap_mac", "ap_location", ["ap_mac"], unique=True)
    op.create_index("ix_ap_location_device_id", "ap_location", ["device_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ap_location_device_id", table_name="ap_location")
    op.drop_index("ix_ap_location_ap_mac", table_name="ap_location")
    op.drop_table("ap_location")
