"""VLAN + VlanSubnet Tabellen (zentrale VLAN-Verwaltung #36)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-28 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "vlan",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vlan_vlan_id", "vlan", ["vlan_id"], unique=True)

    op.create_table(
        "vlan_subnet",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vlan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cidr", postgresql.CIDR(), nullable=False),
        sa.Column("gateway", postgresql.INET(), nullable=True),
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
        sa.ForeignKeyConstraint(["vlan_id"], ["vlan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vlan_id", "site_id", name="uq_vlan_subnet_vlan_site"),
    )
    op.create_index("ix_vlan_subnet_vlan_id", "vlan_subnet", ["vlan_id"])
    op.create_index("ix_vlan_subnet_site_id", "vlan_subnet", ["site_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_vlan_subnet_site_id", table_name="vlan_subnet")
    op.drop_index("ix_vlan_subnet_vlan_id", table_name="vlan_subnet")
    op.drop_table("vlan_subnet")
    op.drop_index("ix_vlan_vlan_id", table_name="vlan")
    op.drop_table("vlan")
