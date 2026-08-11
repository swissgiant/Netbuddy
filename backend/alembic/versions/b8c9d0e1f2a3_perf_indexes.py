"""Performance-Indizes: created_at-Sortierungen + MAC-Join (S67)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-18 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_vlan_survey_run_created_at", "vlan_survey_run", ["created_at"])
    op.create_index("ix_poe_event_created_at", "poe_event", ["created_at"])
    op.create_index("ix_config_backup_created_at", "config_backup", ["created_at"])
    op.create_index("ix_mac_address_entry_interface_id", "mac_address_entry", ["interface_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_mac_address_entry_interface_id", table_name="mac_address_entry")
    op.drop_index("ix_config_backup_created_at", table_name="config_backup")
    op.drop_index("ix_poe_event_created_at", table_name="poe_event")
    op.drop_index("ix_vlan_survey_run_created_at", table_name="vlan_survey_run")
