from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_campus_service
from app.core.config import Settings
from app.models.identity import (
    Campus,
    CampusAppealStatus,
    CampusVerification,
    CampusVerificationAppeal,
    CampusVerificationStatus,
    School,
    SchoolEmailDomain,
)
from app.services.campus import CampusService, domain_matches
from app.services.private_storage import PrivateAppealStorage
from tests.test_auth import auth_test_client, registration_payload


class MemoryCampusRepository:
    def __init__(self) -> None:
        self.schools: dict[UUID, School] = {}
        self.campuses: dict[UUID, Campus] = {}
        self.domains: list[SchoolEmailDomain] = []
        self.verifications: list[CampusVerification] = []
        self.appeals: dict[UUID, CampusVerificationAppeal] = {}
        self.permissions: set[tuple[UUID, str]] = set()

    def register_rollback_callback(self, callback: object) -> None:
        del callback

    async def lock_user(self, user_id: UUID) -> None:
        del user_id

    async def list_schools(self) -> list[School]:
        return list(self.schools.values())

    async def get_school(self, school_id: UUID) -> School | None:
        return self.schools.get(school_id)

    async def get_campus(self, campus_id: UUID) -> Campus | None:
        return self.campuses.get(campus_id)

    async def list_email_domains(self, school_id: UUID) -> list[SchoolEmailDomain]:
        return [item for item in self.domains if item.school_id == school_id and item.is_active]

    async def latest_verification(
        self, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None:
        del for_update
        return next(
            (
                item
                for item in reversed(self.verifications)
                if item.user_id == user_id and item.deleted_at is None
            ),
            None,
        )

    async def verification_for_user(
        self, verification_id: UUID, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None:
        del for_update
        return next(
            (
                item
                for item in self.verifications
                if item.id == verification_id
                and item.user_id == user_id
                and item.deleted_at is None
            ),
            None,
        )

    async def retire_pending_verifications(self, user_id: UUID, *, at: datetime) -> None:
        for item in self.verifications:
            if (
                item.user_id == user_id
                and item.status == CampusVerificationStatus.PENDING
                and item.deleted_at is None
            ):
                item.deleted_at = at

    async def expire_verification(self, verification_id: UUID, *, at: datetime) -> None:
        for item in self.verifications:
            if (
                item.id == verification_id
                and item.status == CampusVerificationStatus.VERIFIED
                and item.expires_at is not None
                and item.expires_at <= at
            ):
                item.status = CampusVerificationStatus.EXPIRED

    async def expire_email_verifications(self, campus_email: str, *, at: datetime) -> None:
        for item in self.verifications:
            if (
                item.campus_email == campus_email
                and item.status == CampusVerificationStatus.VERIFIED
                and item.expires_at is not None
                and item.expires_at <= at
            ):
                item.status = CampusVerificationStatus.EXPIRED

    async def create_verification(self, verification: CampusVerification) -> CampusVerification:
        if any(
            item.campus_email == verification.campus_email
            and item.deleted_at is None
            and item.status
            in {
                CampusVerificationStatus.PENDING,
                CampusVerificationStatus.VERIFIED,
                CampusVerificationStatus.APPEALING,
            }
            for item in self.verifications
        ):
            raise IntegrityError("duplicate campus email", {}, Exception("duplicate"))
        self.verifications.append(verification)
        return verification

    async def save_verification(self, verification: CampusVerification) -> None:
        assert verification in self.verifications

    async def pending_appeal(self, user_id: UUID) -> CampusVerificationAppeal | None:
        return next(
            (
                appeal
                for appeal in self.appeals.values()
                if appeal.user_id == user_id and appeal.status == CampusAppealStatus.PENDING
            ),
            None,
        )

    async def create_appeal(self, appeal: CampusVerificationAppeal) -> CampusVerificationAppeal:
        if await self.pending_appeal(appeal.user_id):
            raise IntegrityError("duplicate appeal", {}, Exception("duplicate"))
        self.appeals[appeal.id] = appeal
        return appeal

    async def get_appeal(self, appeal_id: UUID) -> CampusVerificationAppeal | None:
        return self.appeals.get(appeal_id)

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool:
        return (user_id, permission_code) in self.permissions


class CampusMailerRecorder:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_campus_verification_code(self, *, recipient: str, code: str) -> None:
        self.messages.append((recipient, code))


def seeded_repository() -> tuple[MemoryCampusRepository, School, Campus]:
    repository = MemoryCampusRepository()
    school = School(
        id=uuid4(),
        code="TEST",
        name="测试学校",
        is_active=True,
        deleted_at=None,
        campuses=[],
        email_domains=[],
    )
    campus = Campus(
        id=uuid4(),
        school_id=school.id,
        code="MAIN",
        name="主校区",
        is_active=True,
        deleted_at=None,
    )
    domain = SchoolEmailDomain(
        id=uuid4(),
        school_id=school.id,
        domain="campus.edu",
        allow_subdomains=True,
        is_active=True,
    )
    school.campuses = [campus]
    school.email_domains = [domain]
    repository.schools[school.id] = school
    repository.campuses[campus.id] = campus
    repository.domains.append(domain)
    return repository, school, campus


def campus_client(
    private_root: Path,
) -> tuple[TestClient, MemoryCampusRepository, CampusMailerRecorder, School, Campus]:
    client, _, verification_store, _ = auth_test_client()
    repository, school, campus = seeded_repository()
    mailer = CampusMailerRecorder()
    app = cast(FastAPI, client.app)
    settings = cast(Settings, app.state.settings)
    service = CampusService(
        repository=repository,
        verification_store=verification_store,
        mailer=mailer,
        storage=PrivateAppealStorage(private_root, max_bytes=1024 * 1024),
        settings=settings,
    )
    app.dependency_overrides[get_campus_service] = lambda: service
    return client, repository, mailer, school, campus


def register_user(client: TestClient, email: str = "student@example.com") -> str:
    response = client.post(
        "/api/v1/auth/email-verifications",
        json={"email": email, "purpose": "registration"},
    )
    assert response.status_code == 202
    registered = client.post(
        "/api/v1/auth/register",
        json=registration_payload(email=email),
    )
    assert registered.status_code == 201
    return str(registered.json()["access_token"])


def test_campus_email_flow_and_four_capability_gates(tmp_path: Path) -> None:
    client, repository, mailer, school, campus = campus_client(tmp_path)
    with client:
        access = register_user(client)
        headers = {"Authorization": f"Bearer {access}"}
        schools = client.get("/api/v1/campus/schools")
        policy = client.get("/api/v1/campus/policy")
        for capability in ("publish", "message", "order", "review"):
            blocked = client.get(f"/api/v1/campus/capabilities/{capability}", headers=headers)
            assert blocked.status_code == 403
            assert blocked.json()["code"] == "campus_verification_required"

        requested = client.post(
            "/api/v1/campus/email-verifications",
            headers=headers,
            json={
                "school_id": str(school.id),
                "campus_id": str(campus.id),
                "campus_email": "student@dept.campus.edu",
            },
        )
        confirmed = client.post(
            "/api/v1/campus/email-verifications/confirm",
            headers=headers,
            json={"verification_id": requested.json()["verification_id"], "code": "123456"},
        )
        allowed = client.get("/api/v1/campus/capabilities/publish", headers=headers)

    assert schools.status_code == 200
    assert schools.json()[0]["email_domains"] == ["*.campus.edu"]
    assert policy.json() == {
        "verification_days": 365,
        "appeal_retention_days": 180,
        "appeal_max_bytes": 10 * 1024 * 1024,
        "appeal_media_types": ["application/pdf", "image/png", "image/jpeg"],
    }
    assert requested.status_code == 202
    assert mailer.messages == [("student@dept.campus.edu", "123456")]
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "verified"
    assert allowed.json() == {"capability": "publish", "allowed": True}
    assert repository.verifications[0].expires_at is not None


def test_domain_rules_and_duplicate_active_email(tmp_path: Path) -> None:
    client, repository, _, school, campus = campus_client(tmp_path)
    with client:
        first_access = register_user(client)
        second_access = register_user(client, "other@example.com")
        payload = {
            "school_id": str(school.id),
            "campus_id": str(campus.id),
            "campus_email": "same@campus.edu",
        }
        first = client.post(
            "/api/v1/campus/email-verifications",
            headers={"Authorization": f"Bearer {first_access}"},
            json=payload,
        )
        duplicate = client.post(
            "/api/v1/campus/email-verifications",
            headers={"Authorization": f"Bearer {second_access}"},
            json=payload,
        )
        invalid = client.post(
            "/api/v1/campus/email-verifications",
            headers={"Authorization": f"Bearer {second_access}"},
            json={**payload, "campus_email": "student@campus.edu.evil.com"},
        )
        repository.verifications[0].status = CampusVerificationStatus.VERIFIED
        repository.verifications[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        rebound = client.post(
            "/api/v1/campus/email-verifications",
            headers={"Authorization": f"Bearer {second_access}"},
            json=payload,
        )

    assert first.status_code == 202
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "campus_email_already_bound"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "campus_email_domain_not_allowed"
    assert rebound.status_code == 202
    assert repository.verifications[0].status == CampusVerificationStatus.EXPIRED
    assert domain_matches("dept.campus.edu", "campus.edu", True)
    assert not domain_matches("campus.edu.evil.test", "campus.edu", True)


def test_expired_verification_blocks_access(tmp_path: Path) -> None:
    client, repository, _, school, campus = campus_client(tmp_path)
    with client:
        access = register_user(client)
        # The authenticated user id is available from the access-token-backed /me contract.
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).json()
        verification = CampusVerification(
            id=uuid4(),
            user_id=UUID(me["id"]),
            campus_id=campus.id,
            campus_email="student@campus.edu",
            status=CampusVerificationStatus.VERIFIED,
            verified_at=datetime.now(UTC) - timedelta(days=366),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            rejection_reason=None,
            deleted_at=None,
        )
        repository.verifications.append(verification)
        status = client.get("/api/v1/campus/status", headers={"Authorization": f"Bearer {access}"})
        blocked = client.get(
            "/api/v1/campus/capabilities/order",
            headers={"Authorization": f"Bearer {access}"},
        )

    assert status.json()["status"] == "expired"
    assert verification.status == CampusVerificationStatus.EXPIRED
    assert blocked.status_code == 403


def test_private_appeal_material_owner_reviewer_retention_and_signature(tmp_path: Path) -> None:
    client, repository, _, _, campus = campus_client(tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"private-campus-proof"
    with client:
        owner_access = register_user(client)
        reviewer_access = register_user(client, "reviewer@example.com")
        owner = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_access}"}
        ).json()
        reviewer = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {reviewer_access}"}
        ).json()
        submitted = client.post(
            "/api/v1/campus/appeals",
            headers={"Authorization": f"Bearer {owner_access}"},
            data={
                "campus_id": str(campus.id),
                "reason": "校园邮箱暂时无法接收邮件，请人工核验我的在校身份。",
            },
            files={"material": ("proof.png", png, "image/png")},
        )
        appeal_id = submitted.json()["id"]
        denied = client.get(
            f"/api/v1/campus/appeals/{appeal_id}/material",
            headers={"Authorization": f"Bearer {reviewer_access}"},
        )
        owner_download = client.get(
            f"/api/v1/campus/appeals/{appeal_id}/material",
            headers={"Authorization": f"Bearer {owner_access}"},
        )
        repository.permissions.add((UUID(reviewer["id"]), "campus_appeal:read"))
        reviewer_download = client.get(
            f"/api/v1/campus/appeals/{appeal_id}/material",
            headers={"Authorization": f"Bearer {reviewer_access}"},
        )
        appeal = repository.appeals[UUID(appeal_id)]
        appeal.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        expired = client.get(
            f"/api/v1/campus/appeals/{appeal_id}/material",
            headers={"Authorization": f"Bearer {owner_access}"},
        )
        blank_reason = client.post(
            "/api/v1/campus/appeals",
            headers={"Authorization": f"Bearer {reviewer_access}"},
            data={"campus_id": str(campus.id), "reason": " " * 20},
            files={"material": ("proof.png", png, "image/png")},
        )
        spoofed = client.post(
            "/api/v1/campus/appeals",
            headers={"Authorization": f"Bearer {reviewer_access}"},
            data={
                "campus_id": str(campus.id),
                "reason": "校园邮箱无法使用，尝试提交错误文件类型用于边界测试。",
            },
            files={"material": ("fake.png", b"not-a-png", "image/png")},
        )

    assert submitted.status_code == 201
    assert repository.appeals[UUID(appeal_id)].user_id == UUID(owner["id"])
    assert "campus-appeals" in repository.appeals[UUID(appeal_id)].material_key
    assert denied.status_code == 403
    assert owner_download.content == png
    assert reviewer_download.content == png
    assert expired.status_code == 410
    assert blank_reason.status_code == 422
    assert blank_reason.json()["code"] == "campus_appeal_reason_invalid"
    assert spoofed.status_code == 422
    assert spoofed.json()["code"] == "appeal_material_type_invalid"
