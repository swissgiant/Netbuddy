"""Server- und Storage-Kategorien: physical_server, virtual_server, storage_device, storage_link

Revision ID: a1b2c3d4e5f6
Revises: c9d0e1f2a3b4
Create Date: 2026-10-10 12:00:00.000000

"""



from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7f3a9c1d2e4"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

server_role = postgresql.ENUM(
    "esxi_host",
    "hyperv_host",
    "bare_metal",
    "appliance",
    "unknown",
    name="server_role",
    create_type=False,
)
hardware_status = postgresql.ENUM(
    "ok",
    "warning",
    "critical",
    "unknown",
    name="hardware_status",
    create_type=False,
)
warranty_status = postgresql.ENUM(
    "active",
    "expired",
    "unknown",
    name="warranty_status",
    create_type=False,
)
power_state = postgresql.ENUM(
    "on",
    "off",
    "suspended",
    "unknown",
    name="power_state",
    create_type=False,
)
storage_type = postgresql.ENUM(
    "enterprise_array",
    "nas",
    "backup_target",
    "san_switch",
    "unknown",
    name="storage_type",
    create_type=False,
)
server_kind = postgresql.ENUM(
    "physical",
    "virtual",
    name="storage_server_kind",
    create_type=False,
)

_ALL_ENUMS = (
    server_role,
    hardware_status,
    warranty_status,
    power_state,
    storage_type,
    server_kind,
)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column]:
    return [
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for e in _ALL_ENUMS:
        e.create(bind, checkfirst=True)

    op.create_table(
        "physical_server",
        _uuid_pk(),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("dns_name", sa.String(length=255), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("server_role", server_role, server_default="unknown", nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("service_tag", sa.String(length=128), nullable=True),
        sa.Column("cpu_model", sa.String(length=255), nullable=True),
        sa.Column("cpu_sockets", sa.Integer(), nullable=True),
        sa.Column("cpu_cores", sa.Integer(), nullable=True),
        sa.Column("cpu_threads", sa.Integer(), nullable=True),
        sa.Column("ram_mb", sa.Integer(), nullable=True),
        sa.Column("os_name", sa.String(length=255), nullable=True),
        sa.Column("os_version", sa.String(length=128), nullable=True),
        sa.Column("mgmt_ip", postgresql.INET(), nullable=True),
        sa.Column("oob_type", sa.String(length=32), nullable=True),
        sa.Column(
            "ip_addresses",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("hardware_status", hardware_status, server_default="unknown", nullable=False),
        sa.Column("hardware_detail", sa.Text(), nullable=True),
        sa.Column("warranty_provider", sa.String(length=64), nullable=True),
        sa.Column("warranty_start", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("warranty_status", warranty_status, server_default="unknown", nullable=False),
        sa.Column("warranty_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_physical_server_site_id", "physical_server", ["site_id"])
    op.create_index("ix_physical_server_service_tag", "physical_server", ["service_tag"])
    op.create_index(
        "uq_physical_server_service_tag_active",
        "physical_server",
        ["service_tag"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND service_tag IS NOT NULL"),
    )

    op.create_table(
        "virtual_server",
        _uuid_pk(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dns_name", sa.String(length=255), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("power_state", power_state, server_default="unknown", nullable=False),
        sa.Column("vcpu", sa.Integer(), nullable=True),
        sa.Column("ram_mb", sa.Integer(), nullable=True),
        sa.Column("cluster", sa.String(length=255), nullable=True),
        sa.Column("esxi_host", sa.String(length=255), nullable=True),
        sa.Column("physical_server_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vcenter", sa.String(length=255), nullable=True),
        sa.Column("guest_os", sa.String(length=255), nullable=True),
        sa.Column("vmware_tools", sa.String(length=64), nullable=True),
        sa.Column("disk_count", sa.Integer(), nullable=True),
        sa.Column("disk_total_gb", sa.Integer(), nullable=True),
        sa.Column(
            "disks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "datastores", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "ip_addresses",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "networks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("vm_uuid", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["physical_server_id"], ["physical_server.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_virtual_server_site_id", "virtual_server", ["site_id"])
    op.create_index(
        "ix_virtual_server_physical_server_id", "virtual_server", ["physical_server_id"]
    )
    op.create_index("ix_virtual_server_vm_uuid", "virtual_server", ["vm_uuid"])
    op.create_index(
        "uq_virtual_server_vm_uuid_active",
        "virtual_server",
        ["vm_uuid"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND vm_uuid IS NOT NULL"),
    )

    op.create_table(
        "storage_device",
        _uuid_pk(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dns_name", sa.String(length=255), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storage_type", storage_type, server_default="unknown", nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("service_tag", sa.String(length=128), nullable=True),
        sa.Column("firmware", sa.String(length=128), nullable=True),
        sa.Column("hardware_status", hardware_status, server_default="unknown", nullable=False),
        sa.Column("hardware_detail", sa.Text(), nullable=True),
        sa.Column("disk_count", sa.Integer(), nullable=True),
        sa.Column(
            "disks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("capacity_raw_gb", sa.Integer(), nullable=True),
        sa.Column("capacity_usable_gb", sa.Integer(), nullable=True),
        sa.Column("capacity_used_gb", sa.Integer(), nullable=True),
        sa.Column("mgmt_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "ip_addresses",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "protocols", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "connections", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("warranty_provider", sa.String(length=64), nullable=True),
        sa.Column("warranty_start", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("warranty_status", warranty_status, server_default="unknown", nullable=False),
        sa.Column("warranty_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_device_site_id", "storage_device", ["site_id"])
    op.create_index("ix_storage_device_service_tag", "storage_device", ["service_tag"])
    op.create_index(
        "uq_storage_device_service_tag_active",
        "storage_device",
        ["service_tag"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND service_tag IS NOT NULL"),
    )

    op.create_table(
        "storage_link",
        _uuid_pk(),
        sa.Column("server_kind", server_kind, nullable=False),
        sa.Column("physical_server_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("virtual_server_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storage_device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=True),
        sa.Column("server_endpoint", sa.String(length=255), nullable=True),
        sa.Column("storage_endpoint", sa.String(length=255), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=True),
        sa.Column(
            "extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["physical_server_id"], ["physical_server.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["virtual_server_id"], ["virtual_server.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["storage_device_id"], ["storage_device.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_link_physical_server_id", "storage_link", ["physical_server_id"])
    op.create_index("ix_storage_link_virtual_server_id", "storage_link", ["virtual_server_id"])
    op.create_index("ix_storage_link_storage_device_id", "storage_link", ["storage_device_id"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("storage_link")
    op.drop_table("storage_device")
    op.drop_table("virtual_server")
    op.drop_table("physical_server")
    for e in reversed(_ALL_ENUMS):
        e.drop(bind, checkfirst=True)
