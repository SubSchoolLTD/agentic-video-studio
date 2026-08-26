from __future__ import annotations

import base64
import html
import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import token_hash
from .config import Settings
from .models import EmailToken, User

logger = logging.getLogger(__name__)
_sendpulse_token: str | None = None
_sendpulse_expires_at: datetime | None = None
_test_outbox: dict[tuple[str, str], str] = {}


def _rate_limit(session: Session, email: str, kind: str, settings: Settings) -> None:
    now = datetime.now(UTC)
    recent = session.scalar(
        select(EmailToken)
        .where(EmailToken.email == email, EmailToken.kind == kind)
        .order_by(EmailToken.created_at.desc())
    )
    if recent:
        created = recent.created_at if recent.created_at.tzinfo else recent.created_at.replace(tzinfo=UTC)
        elapsed = (now - created).total_seconds()
        if elapsed < settings.email_min_resend_seconds:
            retry = max(1, int(settings.email_min_resend_seconds - elapsed))
            raise HTTPException(429, "Please wait before requesting another email", headers={"Retry-After": str(retry)})
    count = session.scalar(
        select(func.count()).select_from(EmailToken).where(
            EmailToken.email == email,
            EmailToken.kind == kind,
            EmailToken.created_at >= now - timedelta(hours=1),
        )
    )
    if int(count or 0) >= settings.email_max_per_hour:
        raise HTTPException(429, "Email request limit reached", headers={"Retry-After": "3600"})


def issue_email_token(
    session: Session,
    *,
    user: User,
    kind: str,
    settings: Settings,
    request_ip: str | None,
) -> str:
    _rate_limit(session, user.email, kind, settings)
    raw = secrets.token_urlsafe(36)
    minutes = settings.password_reset_minutes if kind == "password_reset" else settings.email_token_minutes
    session.add(
        EmailToken(
            id=f"emt_{secrets.token_hex(12)}",
            user_id=user.id,
            email=user.email,
            kind=kind,
            token_hash=token_hash(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
            request_ip=(request_ip or "")[:64] or None,
        )
    )
    session.commit()
    if settings.app_env == "test":
        _test_outbox[(user.email, kind)] = raw
    return raw


def consume_email_token(session: Session, raw: str, kind: str) -> EmailToken | None:
    record = session.scalar(
        select(EmailToken).where(EmailToken.token_hash == token_hash(raw), EmailToken.kind == kind)
    )
    if not record or record.used_at is not None:
        return None
    expires = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    record.used_at = datetime.now(UTC)
    session.add(record)
    session.commit()
    return record


def test_token(email: str, kind: str) -> str | None:
    return _test_outbox.get((email.lower(), kind))


def _sendpulse_access_token(settings: Settings) -> str | None:
    global _sendpulse_token, _sendpulse_expires_at
    now = datetime.now(UTC)
    if _sendpulse_token and _sendpulse_expires_at and _sendpulse_expires_at > now:
        return _sendpulse_token
    try:
        response = httpx.post(
            "https://api.sendpulse.com/oauth/access_token",
            json={
                "grant_type": "client_credentials",
                "client_id": settings.sendpulse_id,
                "client_secret": settings.sendpulse_secret,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        _sendpulse_token = str(payload["access_token"])
        _sendpulse_expires_at = now + timedelta(seconds=max(30, int(payload.get("expires_in", 300)) - 30))
        return _sendpulse_token
    except Exception:
        logger.exception("SendPulse authentication failed")
        return None


def send_account_email(
    *,
    user: User,
    kind: str,
    raw_token: str,
    settings: Settings,
) -> bool:
    if settings.email_delivery_mode == "log":
        logger.info("Transactional email queued in log mode: kind=%s recipient_domain=%s", kind, user.email.rpartition("@")[2])
        return True
    token = _sendpulse_access_token(settings)
    if not token:
        return False
    if kind == "verify_email":
        subject = "Confirm your Framewise account"
        link = f"{settings.web_base_url.rstrip('/')}/verify-email?token={raw_token}"
        action = "Confirm email"
        intro = "Confirm your email to activate your private Framewise workspace."
    else:
        subject = "Reset your Framewise password"
        link = f"{settings.web_base_url.rstrip('/')}/reset-password?token={raw_token}"
        action = "Reset password"
        intro = "Use this one-time link to choose a new password."
    safe_name = html.escape(user.display_name)
    safe_link = html.escape(link, quote=True)
    body = f"""<!doctype html>
<html><body style="margin:0;background:#f6f3f7;font-family:Inter,Arial,sans-serif;color:#17131f">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f3f7;padding:36px 16px"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#fff;border:1px solid #e8e1eb;border-radius:20px;overflow:hidden">
<tr><td style="padding:24px 30px;background:#21172b;color:#fff"><div style="font-size:23px;font-weight:800">Framewise</div><div style="margin-top:5px;color:#dcb9e6;font-size:13px">Agentic video studio</div></td></tr>
<tr><td style="padding:34px 30px"><h1 style="margin:0 0 18px;font-size:27px;line-height:1.2">{html.escape(subject)}</h1>
<p style="font-size:16px;line-height:1.6">Hello {safe_name},</p><p style="font-size:16px;line-height:1.6">{html.escape(intro)}</p>
<p style="margin:28px 0"><a href="{safe_link}" style="display:inline-block;padding:14px 22px;border-radius:12px;background:#982eb3;color:#fff;text-decoration:none;font-weight:700">{html.escape(action)}</a></p>
<p style="font-size:13px;line-height:1.6;color:#716979">This secure link expires soon. If the button does not work, copy this address:<br><a href="{safe_link}" style="color:#84269c;word-break:break-all">{safe_link}</a></p>
<p style="margin-top:28px;font-size:13px;color:#716979">If you did not request this email, you can safely ignore it.</p></td></tr>
<tr><td style="padding:18px 30px;background:#faf8fb;color:#837989;font-size:12px">Framewise · studio.subschool.us</td></tr>
</table></td></tr></table></body></html>"""
    base_payload = {
        "subject": subject,
        "from": {"name": settings.email_from_name, "email": settings.email_from_email},
        "to": [{"email": user.email, "name": user.display_name}],
    }
    email_payload = {
        **base_payload,
        "html": base64.b64encode(body.encode()).decode(),
        "text": f"{intro}\n\n{link}",
    }
    try:
        response = httpx.post(
            "https://api.sendpulse.com/smtp/emails",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": email_payload},
            timeout=10,
        )
        if response.status_code < 300:
            return True
        logger.error("SendPulse delivery failed: status=%s", response.status_code)
    except Exception:
        logger.exception("SendPulse delivery failed")
    return False
