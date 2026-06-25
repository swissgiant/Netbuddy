import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from netbuddy.db.base import Base, SoftDeleteMixin, TimestampMixin
from netbuddy.db.types import enum_values


class UserRole(enum.StrEnum):
    ADMIN = "admin"  # alles inkl. Userverwaltung
    OPERATOR = "operator"  # lesen + suchen (validate/discover/onboarding) + Inventar pflegen
    VIEWER = "viewer"  # nur lesen


class User(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    # Bei reinen SSO-(Entra-)Usern gibt es kein lokales Passwort → nullable.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Entra-ID-Subject (oid-Claim): stabile, eindeutige Verknüpfung zum AAD-Konto.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=enum_values),
        nullable=False,
        server_default=text("'viewer'"),
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index(
            "uq_app_user_username_active",
            "username",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_app_user_oidc_subject",
            "oidc_subject",
            unique=True,
            postgresql_where=text("oidc_subject IS NOT NULL AND deleted_at IS NULL"),
        ),
    )


class AuthSession(TimestampMixin, Base):
    """Login-Session: opaker Token, hier nur als SHA-256-Hash abgelegt."""

    __tablename__ = "auth_session"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
