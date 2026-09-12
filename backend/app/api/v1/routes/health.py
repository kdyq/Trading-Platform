from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.services.health import readiness_status

router = APIRouter()


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    result = await readiness_status(request.app)
    status_code = (
        status.HTTP_200_OK if result["status"] == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=result)
