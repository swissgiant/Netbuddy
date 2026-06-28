"""PoE recovery event log (audit + rate-limit history)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-28 10:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "poe_event",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("port", sa.String(length=64), nullable=False),
        sa.Column("ap_mac", sa.String(length=12), nullable=True),
        sa.Column("ap_name", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("status_before", sa.String(length=16), nullable=True),
        sa.Column("status_after", sa.String(length=16), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_poe_event_device_id", "poe_event", ["device_id"])
    op.create_index("ix_poe_event_port", "poe_event", ["port"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_poe_event_port", table_name="poe_event")
    op.drop_index("ix_poe_event_device_id", table_name="poe_event")
    op.drop_table("poe_event")
