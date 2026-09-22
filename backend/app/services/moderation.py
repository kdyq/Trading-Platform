from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import AppError
from app.models.catalog import Product, ProductStatus
from app.models.moderation import ModerationAction, Report, ReportAppeal, ReportStatus
from app.models.trade import CreditEventType
from app.repositories.credit import SqlAlchemyCreditRepository
from app.repositories.moderation import SqlAlchemyModerationRepository
from app.repositories.reports import SqlAlchemyReportRepository
from app.schemas.moderation import (
    ModerationProductList,
    ModerationProductSummary,
    ModerationReportList,
    ModerationReportSummary,
    ReportAppealList,
    ReportAppealResponse,
)
from app.services.report_storage import PrivateReportStorage
from app.services.reports import EvidenceDownload


class ModerationService:
    REVIEW_ROLES = {"REVIEWER", "ADMIN", "SUPER_ADMIN"}

    def __init__(
        self,
        repository: SqlAlchemyModerationRepository,
        credit_repository: SqlAlchemyCreditRepository | None = None,
        report_repository: SqlAlchemyReportRepository | None = None,
        report_storage: PrivateReportStorage | None = None,
    ) -> None:
        self.repository = repository
        self.credit_repository = credit_repository
        self.report_repository = report_repository
        self.report_storage = report_storage

    async def require_reviewer(self, user_id: UUID) -> None:
        if not await self.repository.has_role(user_id, self.REVIEW_ROLES):
            raise AppError(status_code=403, code="moderation_forbidden", message="无审核权限")

    async def list_products(
        self, *, moderator_id: UUID, status: ProductStatus
    ) -> ModerationProductList:
        await self.require_reviewer(moderator_id)
        rows = await self.repository.list_products(status)
        return ModerationProductList(
            items=[self._product(product, seller_name) for product, seller_name in rows]
        )

    async def decide_product(
        self,
        *,
        moderator_id: UUID,
        product_id: UUID,
        action: str,
        expected_version: int,
        reason_code: str,
        public_note: str,
        request_id: str,
    ) -> ModerationProductSummary:
        await self.require_reviewer(moderator_id)
        product = await self.repository.get_product(product_id, lock=True)
        if product is None:
            raise AppError(
                status_code=404, code="moderation_product_not_found", message="商品不存在"
            )
        if product.version != expected_version:
            raise AppError(
                status_code=409, code="product_version_conflict", message="商品已被其他审核员处理"
            )
        before = product.status
        now = datetime.now(UTC)
        if action == "approve":
            self._require_status(product, {ProductStatus.PENDING_REVIEW})
            product.status = ProductStatus.ON_SALE
            product.published_at = product.published_at or now
            record_action = ModerationAction.APPROVE
            title = "商品审核通过"
        elif action == "reject":
            self._require_status(product, {ProductStatus.PENDING_REVIEW})
            product.status = ProductStatus.REJECTED
            record_action = ModerationAction.REJECT
            title = "商品审核未通过"
        elif action == "hide":
            self._require_status(
                product, {ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD}
            )
            product.hidden_from_status = product.status.value
            product.status = ProductStatus.HIDDEN
            record_action = ModerationAction.HIDE
            title = "商品已暂时隐藏"
        elif action == "restore":
            self._require_status(product, {ProductStatus.HIDDEN})
            try:
                restored = ProductStatus(product.hidden_from_status or "")
            except ValueError:
                restored = ProductStatus.PENDING_REVIEW
            if restored not in {ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD}:
                restored = ProductStatus.PENDING_REVIEW
            product.status = restored
            product.hidden_from_status = None
            record_action = ModerationAction.RESTORE
            title = "商品已恢复"
        else:
            raise AppError(
                status_code=422, code="moderation_action_invalid", message="审核动作无效"
            )
        product.moderation_reason_code = reason_code
        product.moderation_public_note = public_note.strip()
        self.repository.record_decision(
            product=product,
            moderator_id=moderator_id,
            action=record_action,
            reason=public_note.strip(),
            request_id=request_id,
            before_status=before,
        )
        await self.repository.notify_seller(
            product=product,
            action=action,
            title=title,
            summary=public_note.strip(),
        )
        seller_name = await self.repository.seller_name(product.seller_id)
        await self.repository.session.flush()
        await self.repository.session.refresh(product, attribute_names=["version", "updated_at"])
        return self._product(product, seller_name)

    async def list_reports(
        self, *, moderator_id: UUID, status: ReportStatus | None
    ) -> ModerationReportList:
        await self.require_reviewer(moderator_id)
        reports = await self.repository.list_reports(status)
        return ModerationReportList(items=[await self._report(item) for item in reports])

    async def decide_report(
        self,
        *,
        moderator_id: UUID,
        report_id: UUID,
        action: str,
        expected_version: int,
        penalty_code: str,
        penalty_points: int,
        public_result: str,
        internal_reason: str,
        evidence_ids: list[UUID],
        request_id: str,
    ) -> ModerationReportSummary:
        await self.require_reviewer(moderator_id)
        report = await self.repository.get_report(report_id, lock=True)
        if report is None:
            raise AppError(
                status_code=404, code="moderation_report_not_found", message="举报不存在"
            )
        if report.version != expected_version:
            raise AppError(
                status_code=409, code="report_version_conflict", message="举报已被其他审核员处理"
            )
        available_evidence = set(await self.repository.report_evidence_ids(report.id))
        if not set(evidence_ids).issubset(available_evidence):
            raise AppError(status_code=422, code="report_evidence_invalid", message="证据引用无效")
        if report.status not in {ReportStatus.OPEN, ReportStatus.REVIEWING}:
            raise AppError(status_code=409, code="invalid_report_state", message="当前举报不能处理")
        before = report.status
        if action == "review":
            report.status = ReportStatus.REVIEWING
            moderation_action = ModerationAction.REVIEW
        elif action == "dismiss":
            report.status = ReportStatus.DISMISSED
            report.resolved_at = datetime.now(UTC)
            report.decision_moderator_id = moderator_id
            moderation_action = ModerationAction.DISMISS
        elif action == "violate":
            if report.subject_user_id is None:
                raise AppError(
                    status_code=409, code="report_subject_missing", message="举报对象无法处罚"
                )
            if not evidence_ids:
                raise AppError(
                    status_code=422, code="report_evidence_required", message="确认违规必须引用证据"
                )
            if penalty_code == "suspend" and not await self.repository.has_role(
                moderator_id, {"ADMIN", "SUPER_ADMIN"}
            ):
                raise AppError(
                    status_code=403,
                    code="high_risk_moderation_forbidden",
                    message="无高风险处罚权限",
                )
            if penalty_code == "suspend":
                await self.repository.suspend_user(report.subject_user_id)
                moderation_action = ModerationAction.SUSPEND
            elif penalty_code == "hide":
                await self.repository.hide_report_product(report)
                moderation_action = ModerationAction.HIDE
            else:
                moderation_action = ModerationAction.WARN
            if penalty_points and self.credit_repository is not None:
                await self.credit_repository.append(
                    user_id=report.subject_user_id,
                    event_type=CreditEventType.REPORT_VIOLATION,
                    source_type="report",
                    reference_id=report.id,
                    delta=-penalty_points,
                    reason=public_result.strip(),
                    actor_id=moderator_id,
                )
            report.status = ReportStatus.RESOLVED
            report.resolved_at = datetime.now(UTC)
            report.decision_moderator_id = moderator_id
        else:
            raise AppError(
                status_code=422, code="moderation_action_invalid", message="举报处理动作无效"
            )
        report.public_result = public_result.strip()
        self.repository.record_report_decision(
            report=report,
            moderator_id=moderator_id,
            action=moderation_action,
            internal_reason=internal_reason.strip(),
            request_id=request_id,
            evidence_ids=evidence_ids,
            before_status=before,
        )
        if self.report_repository is not None:
            self.report_repository.add_event(
                report=report,
                actor_id=moderator_id,
                from_status=before,
                to_status=report.status,
                public_note=public_result.strip(),
                event_data={"evidence_ids": [str(item) for item in evidence_ids]},
            )
        await self.repository.notify_report_user(
            user_id=report.reporter_id,
            report_id=report.id,
            event_key=f"report.status:{report.id}:{report.status.value}:{report.version}",
            title="举报处理进度更新",
            summary=public_result.strip(),
        )
        if report.subject_user_id is not None and action in {"dismiss", "violate"}:
            await self.repository.notify_report_user(
                user_id=report.subject_user_id,
                report_id=report.id,
                event_key=f"report.decision:{report.id}:{report.status.value}:{report.version}",
                title="平台治理决定",
                summary=public_result.strip(),
                target_type="report_appeal",
            )
        await self.repository.session.flush()
        await self.repository.session.refresh(report, attribute_names=["version", "updated_at"])
        return await self._report(report)

    async def download_report_evidence(
        self, *, moderator_id: UUID, report_id: UUID, evidence_id: UUID
    ) -> EvidenceDownload:
        await self.require_reviewer(moderator_id)
        evidence = await self.repository.get_report_evidence(evidence_id)
        if evidence is None or evidence.report_id != report_id or self.report_storage is None:
            raise AppError(
                status_code=404, code="report_evidence_not_found", message="举报证据不存在"
            )
        path = self.report_storage.resolve(evidence.object_key)
        if not path.is_file():
            raise AppError(
                status_code=404, code="report_evidence_not_found", message="举报证据不存在"
            )
        return EvidenceDownload(path, evidence.media_type, evidence.original_filename)

    async def create_appeal(
        self, *, appellant_id: UUID, report_id: UUID, details: str
    ) -> ReportAppealResponse:
        report = await self.repository.get_report(report_id, lock=True)
        if (
            report is None
            or report.subject_user_id != appellant_id
            or report.status != ReportStatus.RESOLVED
            or report.decision_moderator_id is None
        ):
            raise AppError(
                status_code=404, code="appealable_report_not_found", message="可申诉记录不存在"
            )
        appeal, created = await self.repository.create_appeal(
            report=report, appellant_id=appellant_id, details=details.strip()
        )
        if created:
            before = report.status
            report.status = ReportStatus.APPEALED
            if self.report_repository is not None:
                self.report_repository.add_event(
                    report=report,
                    actor_id=appellant_id,
                    from_status=before,
                    to_status=ReportStatus.APPEALED,
                    public_note="被处置用户已提交申诉",
                )
            await self.repository.notify_report_user(
                user_id=report.reporter_id,
                report_id=report.id,
                event_key=f"report.appealed:{report.id}",
                title="举报决定进入申诉复核",
                summary="被处置用户已提交申诉，平台将安排独立复核。",
            )
        await self.repository.session.flush()
        return self._appeal(appeal)

    async def review_appeal(
        self,
        *,
        reviewer_id: UUID,
        appeal_id: UUID,
        action: str,
        reason: str,
        override_reason: str | None,
        request_id: str,
    ) -> ReportAppealResponse:
        await self.require_reviewer(reviewer_id)
        appeal = await self.repository.get_appeal(appeal_id, lock=True)
        if appeal is None or appeal.status != "pending":
            raise AppError(status_code=404, code="appeal_not_found", message="待复核申诉不存在")
        if reviewer_id == appeal.original_moderator_id:
            is_super_admin = await self.repository.has_role(reviewer_id, {"SUPER_ADMIN"})
            if not is_super_admin or not override_reason:
                raise AppError(
                    status_code=403,
                    code="independent_review_required",
                    message="申诉必须由不同审核员复核",
                )
        report = await self.repository.get_report(appeal.report_id, lock=True)
        assert report is not None
        if action == "uphold":
            appeal.status = "upheld"
            report.status = ReportStatus.RESOLVED
            public_note = "申诉复核后维持原处理决定"
        elif action == "reverse":
            appeal.status = "reversed"
            report.status = ReportStatus.DISMISSED
            report.public_result = "申诉成立，原处罚已撤销"
            public_note = report.public_result
            await self.repository.restore_report_product(report)
            if report.subject_user_id is not None:
                await self.repository.activate_user(report.subject_user_id)
                if self.credit_repository is not None:
                    penalty = await self.credit_repository.find_source(
                        report.subject_user_id,
                        CreditEventType.REPORT_VIOLATION,
                        report.id,
                    )
                    if penalty is not None:
                        await self.credit_repository.append(
                            user_id=report.subject_user_id,
                            event_type=CreditEventType.PENALTY_REVERSAL,
                            source_type="appeal",
                            reference_id=appeal.id,
                            delta=-penalty.delta,
                            reason="申诉成立，撤销原信用处罚",
                            actor_id=reviewer_id,
                            reversal_of_id=penalty.id,
                        )
        else:
            raise AppError(
                status_code=422, code="appeal_action_invalid", message="申诉复核动作无效"
            )
        appeal.reviewer_id = reviewer_id
        appeal.review_reason = reason.strip()
        appeal.reviewed_at = datetime.now(UTC)
        self.repository.record_report_decision(
            report=report,
            moderator_id=reviewer_id,
            action=ModerationAction.REVERSE if action == "reverse" else ModerationAction.REVIEW,
            internal_reason=f"{reason.strip()} | override: {override_reason or 'none'}",
            request_id=request_id,
            evidence_ids=[],
            before_status=ReportStatus.APPEALED,
        )
        if self.report_repository is not None:
            self.report_repository.add_event(
                report=report,
                actor_id=reviewer_id,
                from_status=ReportStatus.APPEALED,
                to_status=report.status,
                public_note=public_note,
            )
        for user_id in {report.reporter_id, appeal.appellant_id}:
            await self.repository.notify_report_user(
                user_id=user_id,
                report_id=report.id,
                event_key=f"report.appeal.reviewed:{appeal.id}:{action}",
                title="申诉复核完成",
                summary=public_note,
            )
        await self.repository.session.flush()
        await self.repository.session.refresh(appeal, attribute_names=["version", "updated_at"])
        return self._appeal(appeal)

    async def list_appeals(self, reviewer_id: UUID) -> ReportAppealList:
        await self.require_reviewer(reviewer_id)
        return ReportAppealList(
            items=[self._appeal(item) for item in await self.repository.list_appeals()]
        )

    async def _report(self, report: Report) -> ModerationReportSummary:
        return ModerationReportSummary(
            id=report.id,
            reporter_id=report.reporter_id,
            subject_user_id=report.subject_user_id,
            target_type=report.target_type.value,
            target_id=report.target_id,
            reason_code=report.reason_code,
            details=report.details,
            status=report.status.value,
            public_result=report.public_result,
            version=report.version,
            evidence_ids=await self.repository.report_evidence_ids(report.id),
            created_at=report.created_at,
            updated_at=report.updated_at,
        )

    @staticmethod
    def _appeal(appeal: ReportAppeal) -> ReportAppealResponse:
        return ReportAppealResponse(
            id=appeal.id,
            report_id=appeal.report_id,
            status=appeal.status,
            details=appeal.details,
            review_reason=appeal.review_reason,
            created_at=appeal.created_at,
            updated_at=appeal.updated_at,
        )

    @staticmethod
    def _require_status(product: Product, allowed: set[ProductStatus]) -> None:
        if product.status not in allowed:
            raise AppError(
                status_code=409, code="invalid_product_state", message="当前商品状态不能执行该操作"
            )

    @staticmethod
    def _product(product: Product, seller_name: str) -> ModerationProductSummary:
        return ModerationProductSummary(
            id=product.id,
            seller_id=product.seller_id,
            seller_name=seller_name,
            title=product.title,
            description=product.description,
            price=product.price,
            status=product.status.value,
            version=product.version,
            image_urls=[
                f"/api/v1/market/images/{image.id}/thumbnail"
                for image in sorted(product.images, key=lambda item: item.display_order)
                if image.deleted_at is None
            ],
            moderation_reason_code=product.moderation_reason_code,
            moderation_public_note=product.moderation_public_note,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
