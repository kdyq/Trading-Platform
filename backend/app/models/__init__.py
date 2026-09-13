"""SQLAlchemy 领域模型。"""

from app.models.base import Base
from app.models.catalog import Category, Favorite, Product, ProductImage, ProductStatus
from app.models.identity import (
    Campus,
    CampusVerification,
    CampusVerificationStatus,
    PasswordResetToken,
    Permission,
    Role,
    School,
    User,
    UserSession,
    UserStatus,
    role_permissions,
    user_roles,
)
from app.models.messaging import Conversation, Message
from app.models.moderation import (
    AuditLog,
    ModerationAction,
    ModerationRecord,
    ModerationTargetType,
    Report,
    ReportStatus,
)
from app.models.trade import CreditEventType, CreditLedger, Order, OrderEvent, OrderStatus, Review

__all__ = [
    "Base",
    "AuditLog",
    "Campus",
    "CampusVerification",
    "CampusVerificationStatus",
    "Category",
    "Conversation",
    "CreditEventType",
    "CreditLedger",
    "Favorite",
    "Message",
    "ModerationAction",
    "ModerationRecord",
    "ModerationTargetType",
    "Order",
    "OrderEvent",
    "OrderStatus",
    "Permission",
    "PasswordResetToken",
    "Product",
    "ProductImage",
    "ProductStatus",
    "Report",
    "ReportStatus",
    "Review",
    "Role",
    "School",
    "User",
    "UserSession",
    "UserStatus",
    "role_permissions",
    "user_roles",
]
