from app.core.config import Settings
from app.core.exceptions import AppError


def require_publishing(settings: Settings) -> None:
    if not settings.publishing_enabled:
        raise AppError(status_code=503, code="publishing_paused", message="商品发布已暂停")


def require_trading(settings: Settings) -> None:
    if not settings.trading_enabled:
        raise AppError(status_code=503, code="trading_paused", message="新订单已暂停")
