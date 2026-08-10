from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import Settings
from .models import AuthSession, Resource, User

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def refresh_password_hash(password: str, password_hash: str) -> str | None:
    try:
        return password_hasher.hash(password) if password_hasher.check_needs_rehash(password_hash) else None
    except InvalidHashError:
        return None


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_access_token(user: User, organization_id: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user.id,
        "org": organization_id,
        "typ": "access",
        "ver": user.token_version,
        "jti": secrets.token_hex(12),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_access_token(raw_token: str, settings: Settings) -> dict[str, Any]:
    claims = jwt.decode(
        raw_token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "org", "typ", "ver", "exp", "iat"]},
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    return claims


def active_membership(session: Session, user_id: str, organization_id: str | None = None) -> Resource | None:
    statement = select(Resource).where(
        Resource.kind == "membership",
        Resource.status == "active",
        Resource.data["actor_id"].as_string() == user_id,
    )
    if organization_id:
        statement = statement.where(Resource.organization_id == organization_id)
    return session.scalar(statement.order_by(Resource.created_at.asc()))


def default_project_id(session: Session, organization_id: str) -> str | None:
    project = session.scalar(
        select(Resource)
        .where(
            Resource.kind == "project",
            Resource.organization_id == organization_id,
            Resource.status.not_in(["deleted", "archived"]),
        )
        .order_by(Resource.created_at.asc())
    )
    return project.id if project else None


def create_session(
    session: Session,
    *,
    user: User,
    organization_id: str,
    settings: Settings,
    ip_address: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    raw_refresh = f"avs_rt_{secrets.token_urlsafe(48)}"
    record = AuthSession(
        id=f"ses_{secrets.token_hex(12)}",
        user_id=user.id,
        organization_id=organization_id,
        refresh_token_hash=token_hash(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )
    session.add(record)
    session.commit()
    return {
        "access_token": create_access_token(user, organization_id, settings),
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "refresh_expires_in": settings.refresh_token_days * 86400,
        "organization_id": organization_id,
        "default_project_id": default_project_id(session, organization_id),
    }


def rotate_session(
    session: Session,
    *,
    raw_refresh_token: str,
    settings: Settings,
    ip_address: str | None,
    user_agent: str | None,
) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    current = session.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == token_hash(raw_refresh_token))
        .with_for_update()
    )
    if not current:
        return None
    user = session.get(User, current.user_id)
    if not user or user.status != "active":
        return None
    if current.revoked_at is not None:
        # A rotated token was replayed: invalidate every session for this account.
        session.execute(
            update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now)
        )
        session.commit()
        return None
    expires_at = current.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        current.revoked_at = now
        session.commit()
        return None
    membership = active_membership(session, user.id, current.organization_id)
    if not membership:
        return None
    replacement = create_session(
        session,
        user=user,
        organization_id=current.organization_id,
        settings=settings,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    replacement_record = session.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(replacement["refresh_token"]))
    )
    current.revoked_at = now
    current.replaced_by_session_id = replacement_record.id if replacement_record else None
    current.last_used_at = now
    session.add(current)
    session.commit()
    return replacement


def revoke_all_sessions(session: Session, user_id: str) -> None:
    session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    session.commit()
