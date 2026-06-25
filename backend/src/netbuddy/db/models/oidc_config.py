import uuid

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, TimestampMixin
from netbuddy.db.types import EncryptedString


class OidcConfig(TimestampMixin, Base):
    """Entra-ID-(Azure-AD-)SSO-Konfiguration — Single-Row, über die Admin-Seite gepflegt.

    Bewusst in der DB statt in `.env`: der Admin trägt Tenant/Client/Secret/Gruppen-IDs
    im UI ein, das Client-Secret liegt Fernet-verschlüsselt (`EncryptedString`) at rest.
    Rolle ergibt sich pro Login aus der AAD-Gruppen-Mitgliedschaft (admin/operator/viewer).
    """

    __tablename__ = "oidc_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(EncryptedString(512), nullable=True)
    # Muss exakt der in Entra registrierten Redirect-URI entsprechen (HTTPS, FQDN).
    redirect_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Object-IDs der drei AAD-Sicherheitsgruppen → NetBuddy-Rollen.
    group_admin_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_viewer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
