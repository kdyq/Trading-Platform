from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.identity import (
    Campus,
    CampusAppealStatus,
    CampusVerification,
    CampusVerificationAppeal,
    CampusVerificationStatus,
    School,
)
from app.repositories.campus import CampusRepository
from app.services.auth import AuthContext, normalize_email
from app.services.email_verification import VerificationCodeStore
from app.services.mailer import CampusMailer
from app.services.private_storage import PrivateAppealStorage

APPEAL_REVIEW_PERMISSION = "campus_appeal:read"


@dataclass(frozen=True)
class CampusState:
    status: CampusVerificationStatus
    verification: CampusVerification | None
    appeal: CampusVerificationAppeal | None


@dataclass(frozen=True)
class AppealMaterial:
    path: Path
    filename: str
    media_type: str


class CampusService:
    def __init__(
        self,
        *,
        repository: CampusRepository,
        verification_store: VerificationCodeStore,
        mailer: CampusMailer,
        storage: PrivateAppealStorage,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._verification_store = verification_store
        self._mailer = mailer
        self._storage = storage
        self._settings = settings

    @property
    def max_material_bytes(self) -> int:
        return self._settings.campus_appeal_max_bytes

    @property
    def verification_days(self) -> int:
        return self._settings.campus_verification_days

    @property
    def appeal_retention_days(self) -> int:
        return self._settings.campus_appeal_retention_days

    async def schools(self) -> list[School]:
        return await self._repository.list_schools()

    async def request_email_verification(
        self,
        *,
        user_id: UUID,
        school_id: UUID,
        campus_id: UUID,
        campus_email: str,
        ip_address: str | None,
    ) -> CampusVerification:
        school, campus = await self._validated_school_and_campus(school_id, campus_id)
        del school
        email = normalize_email(campus_email)
        email_domain = email.rpartition("@")[2]
        domains = await self._repository.list_email_domains(school_id)
        if not any(
            domain_matches(email_domain, item.domain, item.allow_subdomains) for item in domains
        ):
            raise AppError(
                status_code=422,
                code="campus_email_domain_not_allowed",
                message="该邮箱不符合所选学校的校园邮箱规则",
            )
        now = datetime.now(UTC)
        await self._repository.lock_user(user_id)
        await self._repository.expire_email_verifications(email, at=now)
        if await self._repository.pending_appeal(user_id) is not None:
            raise AppError(
                status_code=409,
                code="campus_appeal_already_pending",
                message="已有待处理的校园认证申诉",
            )
        current = await self._repository.latest_verification(user_id, for_update=True)
        if current is not None and verification_is_active(current, now=now):
            if current.status == CampusVerificationStatus.VERIFIED:
                raise AppError(
                    status_code=409,
                    code="campus_already_verified",
                    message="校园身份已认证，无需重复提交",
                )
        if current is not None and current.status == CampusVerificationStatus.VERIFIED:
            await self._repository.expire_verification(current.id, at=now)
        await self._repository.retire_pending_verifications(user_id, at=now)
        verification = CampusVerification(
            id=uuid4(),
            user_id=user_id,
            campus_id=campus.id,
            campus_email=email,
            status=CampusVerificationStatus.PENDING,
            verified_at=None,
            expires_at=None,
            rejection_reason=None,
        )
        try:
            await self._repository.create_verification(verification)
        except IntegrityError as exc:
            raise AppError(
                status_code=409,
                code="campus_email_already_bound",
                message="该校园邮箱已绑定其他账户",
            ) from exc
        await self._verification_store.limit(subject=email, scope="campus-email")
        await self._verification_store.limit(subject=str(user_id), scope="campus-user")
        await self._verification_store.limit(subject=ip_address or "unknown", scope="campus-ip")
        purpose = verification_purpose(verification.id)
        code = await self._verification_store.issue(email=email, purpose=purpose)
        try:
            await self._mailer.send_campus_verification_code(recipient=email, code=code)
        except AppError:
            await self._verification_store.discard(email=email, purpose=purpose)
            raise
        return verification

    async def confirm_email_verification(
        self, *, user_id: UUID, verification_id: UUID, code: str
    ) -> CampusVerification:
        await self._repository.lock_user(user_id)
        verification = await self._repository.verification_for_user(
            verification_id, user_id, for_update=True
        )
        if verification is None or verification.status != CampusVerificationStatus.PENDING:
            raise AppError(
                status_code=422,
                code="campus_verification_invalid",
                message="校园认证申请无效或已完成",
            )
        await self._verification_store.consume(
            email=verification.campus_email,
            purpose=verification_purpose(verification.id),
            code=code,
        )
        now = datetime.now(UTC)
        verification.status = CampusVerificationStatus.VERIFIED
        verification.verified_at = now
        verification.expires_at = now + timedelta(days=self._settings.campus_verification_days)
        verification.rejection_reason = None
        await self._repository.save_verification(verification)
        return verification

    async def state(self, user_id: UUID) -> CampusState:
        now = datetime.now(UTC)
        verification = await self._repository.latest_verification(user_id)
        appeal = await self._repository.pending_appeal(user_id)
        if verification is not None and verification_is_active(verification, now=now):
            if verification.status == CampusVerificationStatus.VERIFIED:
                return CampusState(CampusVerificationStatus.VERIFIED, verification, None)
        if (
            verification is not None
            and verification.status == CampusVerificationStatus.VERIFIED
            and not verification_is_active(verification, now=now)
        ):
            await self._repository.expire_verification(verification.id, at=now)
            verification.status = CampusVerificationStatus.EXPIRED
            return CampusState(
                CampusVerificationStatus.APPEALING if appeal else CampusVerificationStatus.EXPIRED,
                verification,
                appeal,
            )
        if appeal is not None:
            return CampusState(CampusVerificationStatus.APPEALING, verification, appeal)
        if verification is None:
            return CampusState(CampusVerificationStatus.UNAPPLIED, None, None)
        return CampusState(verification.status, verification, None)

    async def submit_appeal(
        self,
        *,
        user_id: UUID,
        campus_id: UUID,
        reason: str,
        filename: str | None,
        media_type: str | None,
        content: bytes,
    ) -> CampusVerificationAppeal:
        campus = await self._repository.get_campus(campus_id)
        if campus is None:
            raise AppError(status_code=404, code="campus_not_found", message="未找到所选校区")
        await self._repository.lock_user(user_id)
        state = await self.state(user_id)
        if state.status == CampusVerificationStatus.VERIFIED:
            raise AppError(
                status_code=409,
                code="campus_already_verified",
                message="校园身份已认证，无需提交申诉",
            )
        if state.appeal is not None:
            raise AppError(
                status_code=409,
                code="campus_appeal_already_pending",
                message="已有待处理的校园认证申诉",
            )
        normalized_reason = reason.strip()
        if sum(not character.isspace() for character in normalized_reason) < 20:
            raise AppError(
                status_code=422,
                code="campus_appeal_reason_invalid",
                message="情况说明至少需要 20 个非空白字符",
            )
        await self._repository.retire_pending_verifications(user_id, at=datetime.now(UTC))
        material = self._storage.save(
            user_id=user_id,
            filename=filename,
            declared_media_type=media_type,
            content=content,
        )
        self._repository.register_rollback_callback(lambda: self._storage.remove(material.key))
        appeal = CampusVerificationAppeal(
            id=uuid4(),
            user_id=user_id,
            campus_id=campus.id,
            status=CampusAppealStatus.PENDING,
            reason=normalized_reason,
            material_key=material.key,
            original_filename=material.original_filename,
            media_type=material.media_type,
            size_bytes=material.size_bytes,
            retention_until=datetime.now(UTC)
            + timedelta(days=self._settings.campus_appeal_retention_days),
            reviewed_at=None,
            reviewer_id=None,
            review_reason=None,
        )
        try:
            await self._repository.create_appeal(appeal)
        except IntegrityError as exc:
            self._storage.remove(material.key)
            raise AppError(
                status_code=409,
                code="campus_appeal_already_pending",
                message="已有待处理的校园认证申诉",
            ) from exc
        return appeal

    async def appeal_material(self, *, context: AuthContext, appeal_id: UUID) -> AppealMaterial:
        appeal = await self._repository.get_appeal(appeal_id)
        if appeal is None:
            raise AppError(status_code=404, code="campus_appeal_not_found", message="未找到该申诉")
        if appeal.user_id != context.user.id and not await self._repository.has_permission(
            context.user.id, APPEAL_REVIEW_PERMISSION
        ):
            raise AppError(status_code=403, code="forbidden", message="无权访问该申诉材料")
        if not future(appeal.retention_until, datetime.now(UTC)):
            raise AppError(
                status_code=410,
                code="appeal_material_expired",
                message="申诉材料已超过保存期限",
            )
        path = self._storage.resolve(appeal.material_key)
        if not path.is_file():
            raise AppError(
                status_code=404,
                code="appeal_material_not_found",
                message="未找到申诉材料",
            )
        return AppealMaterial(path, appeal.original_filename, appeal.media_type)

    async def require_verified(self, user_id: UUID) -> None:
        if (await self.state(user_id)).status != CampusVerificationStatus.VERIFIED:
            raise AppError(
                status_code=403,
                code="campus_verification_required",
                message="完成校园认证后才能使用此功能",
            )

    async def _validated_school_and_campus(
        self, school_id: UUID, campus_id: UUID
    ) -> tuple[School, Campus]:
        school = await self._repository.get_school(school_id)
        campus = await self._repository.get_campus(campus_id)
        if school is None:
            raise AppError(status_code=404, code="school_not_found", message="未找到所选学校")
        if campus is None or campus.school_id != school.id:
            raise AppError(status_code=404, code="campus_not_found", message="未找到所选校区")
        return school, campus


def verification_purpose(verification_id: UUID) -> str:
    return f"campus:{verification_id}"


def domain_matches(email_domain: str, configured_domain: str, allow_subdomains: bool) -> bool:
    domain = email_domain.casefold().rstrip(".")
    configured = configured_domain.casefold().rstrip(".")
    return domain == configured or (allow_subdomains and domain.endswith(f".{configured}"))


def verification_is_active(verification: CampusVerification, *, now: datetime) -> bool:
    if verification.status == CampusVerificationStatus.PENDING:
        return True
    return (
        verification.status == CampusVerificationStatus.VERIFIED
        and verification.expires_at is not None
        and future(verification.expires_at, now)
    )


def future(value: datetime, reference: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value > reference
