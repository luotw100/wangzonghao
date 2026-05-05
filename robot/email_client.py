"""Resend email client. HTTP-only, no SDK dependency."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResendConfig:
    api_key: str
    from_address: str   # e.g. "Laborster <noreply@luotw.top>"


class ResendClient:
    BASE_URL = "https://api.resend.com"

    def __init__(self, config: ResendConfig, request_timeout: float = 15.0):
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=request_timeout,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def send_email(self, to: str, subject: str, html: str, text: Optional[str] = None) -> str:
        payload = {
            "from": self._config.from_address,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        resp = await self._client.post("/emails", json=payload)
        if resp.status_code >= 400:
            logger.error("Resend send failed: %s %s", resp.status_code, resp.text)
            resp.raise_for_status()
        data = resp.json()
        return data.get("id", "")

    async def close(self):
        await self._client.aclose()


def render_login_code_email(code: str) -> tuple[str, str]:
    """Return (html, text) bodies for a login code email."""
    html = f"""\
<!doctype html>
<html>
  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#f6f7f9; padding:32px;">
    <div style="max-width:480px; margin:0 auto; background:#fff; border-radius:12px; padding:32px; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
      <h2 style="margin:0 0 16px; color:#111;">Laborster 登录验证码</h2>
      <p style="margin:0 0 24px; color:#444; line-height:1.6;">使用以下验证码登录后台。验证码 <b>5 分钟内有效</b>，仅可使用一次。</p>
      <div style="font-size:32px; letter-spacing:8px; font-weight:700; color:#111; background:#f3f4f6; padding:16px; text-align:center; border-radius:8px;">{code}</div>
      <p style="margin:24px 0 0; color:#888; font-size:13px;">如果这不是你本人发起的登录，请忽略本邮件。</p>
    </div>
  </body>
</html>"""
    text = f"Laborster 登录验证码：{code}\n\n5 分钟内有效，仅可使用一次。\n如非本人操作请忽略。"
    return html, text


def render_account_approved_email() -> tuple[str, str]:
    html = """\
<!doctype html>
<html>
  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#f6f7f9; padding:32px;">
    <div style="max-width:480px; margin:0 auto; background:#fff; border-radius:12px; padding:32px;">
      <h2 style="margin:0 0 16px; color:#111;">账号已通过审批</h2>
      <p style="margin:0; color:#444; line-height:1.6;">你的 Laborster Robot 账号已通过审批，可以登录使用了。</p>
    </div>
  </body>
</html>"""
    text = "你的 Laborster Robot 账号已通过审批，可以登录使用了。"
    return html, text
