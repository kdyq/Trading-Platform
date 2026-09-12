"""SQLAlchemy 领域模型。"""

from app.models.base import Base
from app.models.identity import (
    Campus,
    CampusVerification,
    CampusVerificationStatus,
    Permission,
    Role,
    School,
    User,
    UserSession,
    UserStatus,
    role_permissions,
    user_roles,
)

__all__ = [
    "Base",
    "Campus",
    "CampusVerification",
    "CampusVerificationStatus",
    "Permission",
    "Role",
    "School",
    "User",
    "UserSession",
    "UserStatus",
    "role_permissions",
    "user_roles",
]
