from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.exceptions import AppError


class VerificationMailer(Protocol):
    async def send_verification_code(self, *, recipient: str, code: str) -> None: ...


class UnavailableVerificationMailer:
    async def send_verification_code(self, *, recipient: str, code: str) -> None:
        raise AppError(
            status_code=503,
            code="email_delivery_unavailable",
            message="验证码邮件服务尚未配置",
        )


class QQVerificationMailer:
    def __init__(self, *, username: str, auth_code: str, from_name: str) -> None:
        self._username = username
        self._auth_code = auth_code
        self._from_name = from_name

    async def send_verification_code(self, *, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = f"{self._from_name} <{self._username}>"
        message["To"] = recipient
        message["Subject"] = "拾光集市登录邮箱验证码"
        message.set_content(f"你的验证码是 {code}，10 分钟内有效。请勿转发给他人。")
        try:
            await aiosmtplib.send(
                message,
                hostname="smtp.qq.com",
                port=465,
                username=self._username,
                password=self._auth_code,
                use_tls=True,
                timeout=10,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise AppError(
                status_code=503,
                code="email_delivery_failed",
                message="验证码邮件暂时无法发送，请稍后重试",
            ) from exc
