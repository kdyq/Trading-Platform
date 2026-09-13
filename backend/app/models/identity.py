from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class CampusVerificationStatus(StrEnum):
    UNAPPLIED = "unapplied"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    APPEALING = "appealing"


class CampusAppealStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
)


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True),
)


class School(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "schools"
    __table_args__ = (
        UniqueConstraint("code", name="uq_schools_code"),
        UniqueConstraint("name", name="uq_schools_name"),
    )

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    campuses: Mapped[list["Campus"]] = relationship(back_populates="school")
    email_domains: Mapped[list["SchoolEmailDomain"]] = relationship(back_populates="school")


class SchoolEmailDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "school_email_domains"
    __table_args__ = (
        CheckConstraint("domain = lower(domain)", name="domain_lowercase"),
        UniqueConstraint("domain", name="uq_school_email_domains_domain"),
        Index("ix_school_email_domains_school_id", "school_id"),
    )

    school_id: Mapped[UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    domain: Mapped[str] = mapped_column(String(255))
    allow_subdomains: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    school: Mapped[School] = relationship(back_populates="email_domains")


class Campus(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_campuses_school_code"),
        UniqueConstraint("school_id", "name", name="uq_campuses_school_name"),
    )

    school_id: Mapped[UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    school: Mapped[School] = relationship(back_populates="campuses")
    verifications: Mapped[list["CampusVerification"]] = relationship(back_populates="campus")
    verification_appeals: Mapped[list["CampusVerificationAppeal"]] = relationship(
        back_populates="campus"
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("login_email = lower(login_email)", name="login_email_lowercase"),
        Index(
            "uq_users_login_email",
            func.lower(text("login_email")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_status", "status"),
    )

    login_email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="user_status",
        ),
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    last_login_at: Mapped[datetime | None]
    login_email_verified_at: Mapped[datetime]
    user_agreement_version: Mapped[str] = mapped_column(String(64))
    privacy_policy_version: Mapped[str] = mapped_column(String(64))
    terms_agreed_at: Mapped[datetime]
    avatar_key: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")
    campus_verifications: Mapped[list["CampusVerification"]] = relationship(back_populates="user")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(back_populates="user")
    campus_verification_appeals: Mapped[list["CampusVerificationAppeal"]] = relationship(
        foreign_keys="CampusVerificationAppeal.user_id", back_populates="user"
    )


class CampusVerification(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "campus_verifications"
    __table_args__ = (
        CheckConstraint("campus_email = lower(campus_email)", name="campus_email_lowercase"),
        Index("ix_campus_verifications_user_id", "user_id"),
        Index("ix_campus_verifications_campus_id", "campus_id"),
        Index("ix_campus_verifications_status", "status"),
        Index(
            "uq_campus_verifications_active_email",
            func.lower(text("campus_email")),
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('pending', 'verified', 'appealing')"
            ),
        ),
        Index(
            "uq_campus_verifications_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('pending', 'verified', 'appealing')"
            ),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    campus_id: Mapped[UUID] = mapped_column(ForeignKey("campuses.id", ondelete="RESTRICT"))
    campus_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[CampusVerificationStatus] = mapped_column(
        Enum(
            CampusVerificationStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="campus_verification_status",
        ),
        default=CampusVerificationStatus.UNAPPLIED,
        server_default=CampusVerificationStatus.UNAPPLIED.value,
    )
    verified_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="campus_verifications")
    campus: Mapped[Campus] = relationship(back_populates="verifications")


class CampusVerificationAppeal(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "campus_verification_appeals"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="material_size_positive"),
        Index("ix_campus_verification_appeals_user_id", "user_id"),
        Index("ix_campus_verification_appeals_status", "status"),
        Index("ix_campus_verification_appeals_retention_until", "retention_until"),
        Index(
            "uq_campus_verification_appeals_pending_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    campus_id: Mapped[UUID] = mapped_column(ForeignKey("campuses.id", ondelete="RESTRICT"))
    status: Mapped[CampusAppealStatus] = mapped_column(
        Enum(
            CampusAppealStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="campus_appeal_status",
        ),
        default=CampusAppealStatus.PENDING,
        server_default=CampusAppealStatus.PENDING.value,
    )
    reason: Mapped[str] = mapped_column(Text)
    material_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int]
    retention_until: Mapped[datetime]
    reviewed_at: Mapped[datetime | None]
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    review_reason: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(
        foreign_keys=[user_id], back_populates="campus_verification_appeals"
    )
    campus: Mapped[Campus] = relationship(back_populates="verification_appeals")
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])


class Role(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"),)

    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"),)

    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class UserSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("refresh_token_digest", name="uq_user_sessions_refresh_token_digest"),
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_family_id", "family_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    family_id: Mapped[UUID]
    refresh_token_digest: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime]
    authenticated_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_password_reset_tokens_digest"),
        Index("ix_password_reset_tokens_user_id", "user_id"),
        Index("ix_password_reset_tokens_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    token_digest: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")
