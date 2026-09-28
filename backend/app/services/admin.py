from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.permissions import ROLE_PERMISSIONS, STAFF_ROLES
from app.models.catalog import Category, Product, ProductStatus
from app.models.identity import (
    Campus,
    CampusAppealStatus,
    CampusVerification,
    CampusVerificationAppeal,
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
from app.models.moderation import AuditLog
from app.models.notification import Notification
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.schemas.admin import (
    AdminCapabilities,
    CampusAppealListAdmin,
    CampusAppealSummaryAdmin,
    CampusListAdmin,
    CategoryListAdmin,
    ProductListAdmin,
    ProductSummaryAdmin,
    StaffList,
    StaffSummary,
    UserListAdmin,
    UserSummaryAdmin,
)
from app.schemas.catalog import AdminCampusResponse, AdminCategoryResponse
from app.services.auth import AuthContext


def masked_email(email: str | None) -> str | None:
    if email is None:
        return None
    name, separator, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if separator else "***"


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def capabilities(self, context: AuthContext) -> AdminCapabilities:
        rows = (
            await self.session.execute(
                select(Role.code, Permission.code)
                .select_from(user_roles)
                .join(Role, Role.id == user_roles.c.role_id)
                .outerjoin(role_permissions, role_permissions.c.role_id == Role.id)
                .outerjoin(Permission, Permission.id == role_permissions.c.permission_id)
                .where(user_roles.c.user_id == context.user.id, Role.deleted_at.is_(None))
            )
        ).all()
        roles = sorted({role for role, _ in rows}) or ["USER"]
        permissions = sorted({permission for _, permission in rows if permission is not None})
        forced = bool(context.user.must_change_password)
        return AdminCapabilities(
            roles=roles,
            permissions=[] if forced else permissions,
            must_change_password=forced,
        )

    async def require(
        self, context: AuthContext, permission: str, *, high_risk: bool = False
    ) -> None:
        if context.user.must_change_password:
            raise AppError(
                status_code=403,
                code="password_change_required",
                message="请先修改初始密码",
            )
        found = await self.session.scalar(
            select(Permission.id)
            .select_from(user_roles)
            .join(Role, Role.id == user_roles.c.role_id)
            .join(role_permissions, role_permissions.c.role_id == Role.id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(
                user_roles.c.user_id == context.user.id,
                Role.deleted_at.is_(None),
                Permission.code == permission,
            )
            .limit(1)
        )
        if found is None:
            raise AppError(status_code=403, code="permission_denied", message="无权执行此操作")
        if high_risk:
            authenticated_at = context.claims.authenticated_at
            if authenticated_at.tzinfo is None:
                authenticated_at = authenticated_at.replace(tzinfo=UTC)
            if authenticated_at < datetime.now(UTC) - timedelta(
                minutes=self.settings.recent_auth_minutes
            ):
                raise AppError(
                    status_code=403,
                    code="recent_authentication_required",
                    message="请重新登录后再执行此操作",
                )

    async def staff(self, context: AuthContext, *, page: int, page_size: int) -> StaffList:
        await self.require(context, "staff:manage")
        staff_ids = (
            select(user_roles.c.user_id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(Role.code.in_(STAFF_ROLES), Role.deleted_at.is_(None))
            .distinct()
        )
        filtered = select(User).where(User.id.in_(staff_ids), User.deleted_at.is_(None))
        total = int(
            await self.session.scalar(select(func.count()).select_from(filtered.subquery())) or 0
        )
        users = list(
            (
                await self.session.scalars(
                    filtered.order_by(User.created_at.desc(), User.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        mapping = await self._role_mapping([user.id for user in users])
        return StaffList(
            items=[
                StaffSummary(
                    id=user.id,
                    username=user.username,
                    email=user.login_email,
                    display_name=user.display_name,
                    status=user.status,
                    roles=mapping.get(user.id, []),
                    created_at=user.created_at,
                )
                for user in users
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def invite_existing(
        self, context: AuthContext, *, email: str, role_code: str, reason: str
    ) -> StaffSummary:
        await self.require(context, "staff:manage", high_risk=True)
        self._validate_staff_roles({role_code})
        await self._staff_lock()
        user = await self.session.scalar(
            select(User)
            .where(User.login_email == email.lower(), User.deleted_at.is_(None))
            .with_for_update()
        )
        if user is None:
            raise AppError(
                status_code=404,
                code="account_registration_required",
                message="该邮箱需先完成普通账户注册与邮箱验证",
            )
        if user.id == context.user.id:
            raise AppError(status_code=409, code="self_role_change", message="不能修改自己的角色")
        existing = set((await self._role_mapping([user.id])).get(user.id, []))
        if existing & STAFF_ROLES:
            raise AppError(status_code=409, code="already_staff", message="该账户已有后台角色")
        role = await self.session.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            raise AppError(status_code=503, code="roles_not_seeded", message="后台角色未初始化")
        await self.session.execute(insert(user_roles).values(user_id=user.id, role_id=role.id))
        await self._revoke_sessions(user.id)
        self._notify_staff(user.id, "后台角色邀请", "你已获得后台角色，请重新登录后查看权限。")
        await self._audit(
            context.user.id,
            "staff.invite",
            "user",
            user.id,
            {
                "before_roles": sorted(existing),
                "after_roles": sorted(existing | {role_code}),
                "reason": reason,
            },
        )
        await self.session.flush()
        return self._staff_summary(user, sorted(existing | {role_code}))

    async def set_staff_roles(
        self, context: AuthContext, target_id: UUID, *, roles: list[str], reason: str
    ) -> StaffSummary:
        await self.require(context, "staff:manage", high_risk=True)
        desired = set(roles)
        self._validate_staff_roles(desired)
        if target_id == context.user.id:
            raise AppError(status_code=409, code="self_role_change", message="不能修改自己的角色")
        await self._staff_lock()
        user = await self._staff_user_for_update(target_id)
        before = set((await self._role_mapping([target_id])).get(target_id, []))
        if not before & STAFF_ROLES:
            raise AppError(status_code=404, code="staff_not_found", message="后台人员不存在")
        await self._protect_last_super(user, before, desired)
        role_rows = (
            await self.session.execute(select(Role.id, Role.code).where(Role.code.in_(desired)))
        ).all()
        if len(role_rows) != len(desired):
            raise AppError(status_code=503, code="roles_not_seeded", message="后台角色未初始化")
        await self.session.execute(delete(user_roles).where(user_roles.c.user_id == target_id))
        for role_id, _ in role_rows:
            await self.session.execute(
                insert(user_roles).values(user_id=target_id, role_id=role_id)
            )
        await self._revoke_sessions(target_id)
        self._notify_staff(target_id, "后台角色已变更", "你的后台角色已调整，请重新登录。")
        await self._audit(
            context.user.id,
            "staff.roles",
            "user",
            target_id,
            {"before_roles": sorted(before), "after_roles": sorted(desired), "reason": reason},
        )
        await self.session.flush()
        return self._staff_summary(user, sorted(desired))

    async def set_status(
        self,
        context: AuthContext,
        target_id: UUID,
        *,
        status: UserStatus,
        reason: str,
        staff_only: bool,
    ) -> StaffSummary | UserSummaryAdmin:
        await self.require(
            context, "staff:manage" if staff_only else "users:status", high_risk=True
        )
        if target_id == context.user.id:
            raise AppError(status_code=409, code="self_status_change", message="不能修改自己的状态")
        await self._staff_lock()
        user = await self._staff_user_for_update(target_id)
        roles = set((await self._role_mapping([target_id])).get(target_id, []))
        if staff_only and not roles & STAFF_ROLES:
            raise AppError(status_code=404, code="staff_not_found", message="后台人员不存在")
        if not staff_only and roles & STAFF_ROLES:
            raise AppError(
                status_code=403,
                code="staff_status_requires_super_admin",
                message="后台人员状态需由超级管理员操作",
            )
        if status not in {UserStatus.ACTIVE, UserStatus.DISABLED}:
            raise AppError(
                status_code=422,
                code="status_not_manageable",
                message="此处仅支持启用或停用账户",
            )
        if user.status == UserStatus.SUSPENDED:
            raise AppError(
                status_code=409,
                code="suspension_review_required",
                message="处罚暂停中的账户需经举报申诉流程处理",
            )
        if status == user.status:
            raise AppError(status_code=409, code="status_unchanged", message="状态未变化")
        await self._protect_last_super(user, roles, roles if status == UserStatus.ACTIVE else set())
        previous = user.status
        user.status = status
        await self._revoke_sessions(user.id)
        self._notify_staff(user.id, "账户状态已变更", "你的账户状态已调整，请查看平台通知。")
        await self._audit(
            context.user.id,
            "staff.status" if staff_only else "user.status",
            "user",
            user.id,
            {"before_status": previous.value, "after_status": status.value, "reason": reason},
        )
        await self.session.flush()
        if staff_only:
            return self._staff_summary(user, sorted(roles))
        return await self._user_summary(user, email_visible=await self._can_see_email(context))

    async def users(
        self,
        context: AuthContext,
        *,
        query: str | None,
        status: UserStatus | None,
        page: int,
        page_size: int,
    ) -> UserListAdmin:
        await self.require(context, "users:read")
        email_visible = await self._can_see_email(context)
        filters: list[ColumnElement[bool]] = [User.deleted_at.is_(None)]
        if query:
            needle = query.strip().replace("%", "\\%").replace("_", "\\_")
            name_match = User.display_name.ilike(f"%{needle}%", escape="\\")
            filters.append(
                name_match | User.login_email.ilike(f"%{needle}%", escape="\\")
                if email_visible
                else name_match
            )
        if status is not None:
            filters.append(User.status == status)
        total = int(
            await self.session.scalar(select(func.count()).select_from(User).where(*filters)) or 0
        )
        users = list(
            (
                await self.session.scalars(
                    select(User)
                    .where(*filters)
                    .order_by(User.created_at.desc(), User.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return UserListAdmin(
            items=[await self._user_summary(user, email_visible=email_visible) for user in users],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def products(
        self,
        context: AuthContext,
        *,
        query: str | None,
        status: ProductStatus | None,
        page: int,
        page_size: int,
    ) -> ProductListAdmin:
        await self.require(context, "products:read")
        filters: list[ColumnElement[bool]] = [Product.deleted_at.is_(None)]
        if query:
            needle = query.strip().replace("%", "\\%").replace("_", "\\_")
            filters.append(Product.title.ilike(f"%{needle}%", escape="\\"))
        if status is not None:
            filters.append(Product.status == status)
        total = int(
            await self.session.scalar(select(func.count()).select_from(Product).where(*filters))
            or 0
        )
        rows = (
            await self.session.execute(
                select(Product, User.display_name)
                .join(User, User.id == Product.seller_id)
                .where(*filters)
                .order_by(Product.created_at.desc(), Product.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return ProductListAdmin(
            items=[
                ProductSummaryAdmin(
                    id=product.id,
                    title=product.title,
                    seller_id=product.seller_id,
                    seller_name=seller_name,
                    status=product.status,
                    report_penalty_active=product.moderation_source_report_id is not None,
                    price=str(product.price),
                    version=product.version,
                    created_at=product.created_at,
                )
                for product, seller_name in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def categories(
        self, context: AuthContext, *, page: int, page_size: int
    ) -> CategoryListAdmin:
        await self.require(context, "catalog:read")
        total = int(await self.session.scalar(select(func.count()).select_from(Category)) or 0)
        rows = (
            await self.session.scalars(
                select(Category)
                .order_by(Category.display_order, Category.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return CategoryListAdmin(
            items=[
                AdminCategoryResponse.model_validate(item, from_attributes=True) for item in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def campuses(self, context: AuthContext, *, page: int, page_size: int) -> CampusListAdmin:
        await self.require(context, "catalog:read")
        total = int(await self.session.scalar(select(func.count()).select_from(Campus)) or 0)
        rows = (
            await self.session.execute(
                select(Campus, School.name)
                .join(School, School.id == Campus.school_id)
                .order_by(Campus.display_order, Campus.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return CampusListAdmin(
            items=[
                AdminCampusResponse(
                    id=item.id,
                    school_id=item.school_id,
                    school_name=school_name,
                    code=item.code,
                    name=item.name,
                    display_order=item.display_order,
                    is_active=item.is_active,
                    deleted_at=item.deleted_at,
                    version=item.version,
                )
                for item, school_name in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def campus_appeals(
        self, context: AuthContext, *, status: CampusAppealStatus | None, page: int, page_size: int
    ) -> CampusAppealListAdmin:
        await self.require(context, "campus_appeal:read")
        filters: list[ColumnElement[bool]] = []
        if status is not None:
            filters.append(CampusVerificationAppeal.status == status)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(CampusVerificationAppeal).where(*filters)
            )
            or 0
        )
        appeals = (
            await self.session.scalars(
                select(CampusVerificationAppeal)
                .where(*filters)
                .order_by(
                    CampusVerificationAppeal.created_at.desc(),
                    CampusVerificationAppeal.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return CampusAppealListAdmin(
            items=[self._appeal_summary(item) for item in appeals],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def decide_campus_appeal(
        self, context: AuthContext, appeal_id: UUID, *, action: str, reason: str
    ) -> CampusAppealSummaryAdmin:
        await self.require(context, "campus_appeal:review", high_risk=True)
        appeal = await self.session.scalar(
            select(CampusVerificationAppeal)
            .where(CampusVerificationAppeal.id == appeal_id)
            .with_for_update()
        )
        if appeal is None:
            raise AppError(status_code=404, code="campus_appeal_not_found", message="申诉不存在")
        if appeal.status != CampusAppealStatus.PENDING:
            raise AppError(status_code=409, code="appeal_already_reviewed", message="申诉已处理")
        now = datetime.now(UTC)
        if action == "approve":
            verification = await self.session.scalar(
                select(CampusVerification)
                .where(
                    CampusVerification.user_id == appeal.user_id,
                    CampusVerification.campus_id == appeal.campus_id,
                    CampusVerification.deleted_at.is_(None),
                )
                .order_by(CampusVerification.created_at.desc(), CampusVerification.id.desc())
                .limit(1)
                .with_for_update()
            )
            if verification is None or verification.status not in {
                CampusVerificationStatus.EXPIRED,
                CampusVerificationStatus.REJECTED,
            }:
                raise AppError(
                    status_code=409,
                    code="verified_email_required",
                    message="缺少可复核的校园邮箱记录，需先完成邮箱验证",
                )
            verification.status = CampusVerificationStatus.VERIFIED
            verification.verified_at = now
            verification.expires_at = now + timedelta(days=self.settings.campus_verification_days)
            appeal.status = CampusAppealStatus.APPROVED
        elif action == "reject":
            appeal.status = CampusAppealStatus.REJECTED
        else:
            raise AppError(status_code=422, code="invalid_decision", message="复核决定无效")
        appeal.reviewed_at = now
        appeal.reviewer_id = context.user.id
        appeal.review_reason = reason
        await self._audit(
            context.user.id,
            f"campus_appeal.{action}",
            "campus_appeal",
            appeal.id,
            {"before_status": "pending", "after_status": appeal.status.value, "reason": reason},
        )
        await self.session.flush()
        return self._appeal_summary(appeal)

    @staticmethod
    def _appeal_summary(appeal: CampusVerificationAppeal) -> CampusAppealSummaryAdmin:
        return CampusAppealSummaryAdmin(
            id=appeal.id,
            user_id=appeal.user_id,
            campus_id=appeal.campus_id,
            status=appeal.status.value,
            reason=appeal.reason,
            original_filename=appeal.original_filename,
            created_at=appeal.created_at,
            reviewed_at=appeal.reviewed_at,
            review_reason=appeal.review_reason,
        )

    async def _user_summary(self, user: User, *, email_visible: bool) -> UserSummaryAdmin:
        # Campus email and private material are never part of this general-purpose projection.
        campus_status = await SqlAlchemyIdentityRepository(
            self.session
        ).get_campus_verification_status(user.id)
        return UserSummaryAdmin(
            id=user.id,
            username=user.username,
            email=user.login_email if email_visible else masked_email(user.login_email),
            display_name=user.display_name,
            status=user.status,
            campus_status=campus_status.value,
            created_at=user.created_at,
        )

    async def _can_see_email(self, context: AuthContext) -> bool:
        return (
            await self.session.scalar(
                select(Role.id)
                .select_from(user_roles)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(user_roles.c.user_id == context.user.id, Role.code == "SUPER_ADMIN")
                .limit(1)
            )
        ) is not None

    async def _role_mapping(self, ids: list[UUID]) -> dict[UUID, list[str]]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(user_roles.c.user_id, Role.code)
                .select_from(user_roles)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(user_roles.c.user_id.in_(ids), Role.deleted_at.is_(None))
            )
        ).all()
        mapping: dict[UUID, list[str]] = {}
        for user_id, code in rows:
            mapping.setdefault(user_id, []).append(code)
        return mapping

    async def _staff_user_for_update(self, user_id: UUID) -> User:
        user = await self.session.scalar(
            select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update()
        )
        if user is None:
            raise AppError(status_code=404, code="user_not_found", message="用户不存在")
        return user

    async def _staff_lock(self) -> None:
        # Serializes all staff/status mutations, including last-super-admin checks.
        await self.session.execute(select(func.pg_advisory_xact_lock(9350901)))

    async def _protect_last_super(self, user: User, before: set[str], desired: set[str]) -> None:
        if (
            "SUPER_ADMIN" not in before
            or "SUPER_ADMIN" in desired
            or user.status != UserStatus.ACTIVE
        ):
            return
        count = await self.session.scalar(
            select(func.count())
            .select_from(User)
            .join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                Role.code == "SUPER_ADMIN",
                User.status == UserStatus.ACTIVE,
                User.deleted_at.is_(None),
            )
        )
        if int(count or 0) <= 1:
            raise AppError(
                status_code=409,
                code="last_super_admin",
                message="不能停用或移除最后一位有效超级管理员",
            )

    async def _revoke_sessions(self, user_id: UUID) -> None:
        await self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def _audit(
        self,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: UUID,
        data: dict[str, object],
    ) -> None:
        self.session.add(
            AuditLog(
                id=uuid4(),
                actor_id=actor_id,
                request_id=None,
                action=action,
                target_type=target_type,
                target_id=target_id,
                audit_data=data,
            )
        )

    def _notify_staff(self, user_id: UUID, title: str, summary: str) -> None:
        self.session.add(
            Notification(
                id=uuid4(),
                user_id=user_id,
                event_key=f"admin:{uuid4().hex}",
                category="system",
                title=title,
                summary=summary,
                target_type="account",
                target_id=user_id,
                read_at=None,
            )
        )

    @staticmethod
    def _validate_staff_roles(roles: set[str]) -> None:
        if not roles or not roles <= STAFF_ROLES or not roles <= ROLE_PERMISSIONS.keys():
            raise AppError(status_code=422, code="invalid_role", message="后台角色无效")

    @staticmethod
    def _staff_summary(user: User, roles: list[str]) -> StaffSummary:
        return StaffSummary(
            id=user.id,
            username=user.username,
            email=user.login_email,
            display_name=user.display_name,
            status=user.status,
            roles=roles,
            created_at=user.created_at,
        )
