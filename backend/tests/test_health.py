from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_live_does_not_require_dependencies() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_ready_reports_each_missing_dependency() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {
            "database": {"status": "unavailable", "reason": "not_configured"},
            "redis": {"status": "unavailable", "reason": "not_configured"},
        },
    }


def test_http_error_uses_public_contract() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))

    @app.get("/test-error")
    async def test_error() -> None:
        raise HTTPException(status_code=403, detail="没有权限执行此操作")

    with TestClient(app) as client:
        response = client.get("/test-error", headers={"x-request-id": "test-request"})

    assert response.status_code == 403
    assert response.json() == {
        "code": "http_403",
        "message": "没有权限执行此操作",
        "request_id": "test-request",
    }
