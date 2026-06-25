"""Entra-ID SSO: oidc_config table + app_user oidc columns

Revision ID: a1b2c3d4e5f6
Revises: 8c7971315c66
Create Date: 2026-06-25 09:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8c7971315c66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oidc_config",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("client_secret", sa.String(length=512), nullable=True),
        sa.Column("redirect_uri", sa.String(length=512), nullable=True),
        sa.Column("group_admin_id", sa.String(length=64), nullable=True),
        sa.Column("group_operator_id", sa.String(length=64), nullable=True),
        sa.Column("group_viewer_id", sa.String(length=64), nullable=True),
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

    op.add_column("app_user", sa.Column("oidc_subject", sa.String(length=255), nullable=True))
    op.add_column("app_user", sa.Column("email", sa.String(length=255), nullable=True))
    op.alter_column("app_user", "password_hash", existing_type=sa.String(length=255), nullable=True)
    op.create_index(
        "uq_app_user_oidc_subject",
        "app_user",
        ["oidc_subject"],
        unique=True,
        postgresql_where=sa.text("oidc_subject IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_app_user_oidc_subject", table_name="app_user")
    op.alter_column(
        "app_user", "password_hash", existing_type=sa.String(length=255), nullable=False
    )
    op.drop_column("app_user", "email")
    op.drop_column("app_user", "oidc_subject")
    op.drop_table("oidc_config")
