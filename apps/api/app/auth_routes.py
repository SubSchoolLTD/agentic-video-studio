from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    active_membership,
    create_session,
    hash_password,
    refresh_password_hash,
    revoke_all_sessions,
    rotate_session,
    token_hash,
    verify_password,
)
from .billing import charge_feature, grant_signup_credit
from .config import Settings, get_settings
from .database import get_db
from .email_service import consume_email_token, issue_email_token, send_account_email, test_token
from .models import AuthSession, Resource, User, Wallet
from .security import validate_public_url

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=2, max_length=160)
    organization_name: str = Field(min_length=2, max_length=120)
    project_name: str = Field(min_length=2, max_length=120)
    website_url: HttpUrl
    default_language: str = Field(default="en", min_length=2, max_length=12)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class LoginRequest(BaseModel):
    email: str
    password: str


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetConfirm(TokenRequest):
    password: str = Field(min_length=10, max_length=128)


def _normalize_email(raw: str) -> str:
    try:
        return validate_email(raw, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise HTTPException(422, "Enter a valid email address") from exc


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:56]
    return slug or "workspace"


def _request_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _user_payload(user: User, organization_id: str, role: str, project_id: str | None) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "email_verified": user.email_verified_at is not None,
        "is_platform_admin": bool(user.is_platform_admin),
        "organization_id": organization_id,
        "role": role,
        "default_project_id": project_id,
    }


@router.post("/register", status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    email = _normalize_email(payload.email)
    try:
        validate_public_url(str(payload.website_url), resolve_dns=False)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user_id = f"usr_{secrets.token_hex(12)}"
    organization_id = f"org_{secrets.token_hex(12)}"
    project_id = f"prj_{secrets.token_hex(12)}"
    org_slug = _slug(payload.organization_name)
    if session.scalar(select(Resource).where(Resource.kind == "organization", Resource.data["slug"].as_string() == org_slug)):
        org_slug = f"{org_slug[:47]}-{secrets.token_hex(4)}"
    project_slug = _slug(payload.project_name)
    now = datetime.now(UTC)
    user = User(
        id=user_id,
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        status="pending_verification",
    )
    organization = Resource(
        id=organization_id,
        organization_id=organization_id,
        project_id=None,
        kind="organization",
        status="active",
        data={"name": payload.organization_name.strip(), "slug": org_slug, "timezone": payload.timezone, "owner_actor_id": user_id},
    )
    membership = Resource(
        id=f"mem_{secrets.token_hex(12)}",
        organization_id=organization_id,
        project_id=None,
        kind="membership",
        status="active",
        data={"actor_id": user_id, "role": "owner", "project_scope": ["*"]},
    )
    project = Resource(
        id=project_id,
        organization_id=organization_id,
        project_id=project_id,
        kind="project",
        status="active",
        data={
            "name": payload.project_name.strip(),
            "slug": project_slug,
            "website_url": str(payload.website_url),
            "default_language": payload.default_language,
            "regions": [],
            "timezone": payload.timezone,
            "automation_mode": "manual",
            "autopilot_paused": False,
            "rights_confirmed": True,
            "brand_profile_version": 1,
            "settings": {},
        },
    )
    brand_profile = Resource(
        id=f"brand_{secrets.token_hex(12)}",
        organization_id=organization_id,
        project_id=project_id,
        kind="brand_profile",
        status="review_required",
        data={
            "identity": {
                "name": payload.project_name.strip(),
                "website": str(payload.website_url),
                "description": "Review and complete this starter brand profile before publishing.",
                "languages": [payload.default_language],
                "regions": [],
            },
            "audiences": {"primary": [], "secondary": []},
            "value_propositions": [],
            "tone": {"traits": ["clear", "credible"], "prohibited_traits": ["misleading", "guaranteed outcomes"]},
            "claims": {"allowed": [], "require_source": ["performance and outcome claims"], "prohibited": []},
            "visual": {"palette": [], "logo_assets": [], "fonts": [], "references": [], "forbidden_styles": []},
            "cta": {"primary": "Learn more", "alternatives": [], "target_urls": [str(payload.website_url)]},
            "compliance": {"high_risk_topics": [], "mandatory_disclosures": ["Synthetic media where required"]},
            "source_policy": {"trusted_domains": [], "blocked_domains": [], "max_source_age_days": 90},
            "confirmed": False,
            "confidence": 0.25,
        },
    )
    source = Resource(
        id=f"src_{secrets.token_hex(12)}",
        organization_id=organization_id,
        project_id=project_id,
        kind="source",
        status="healthy",
        data={
            "type": "website",
            "name": f"{payload.project_name.strip()} website",
            "url": str(payload.website_url),
            "trust_level": "owned",
            "generation_policy": "research_then_approval",
        },
    )
    subscription = Resource(
        id=f"onb_{secrets.token_hex(12)}",
        organization_id=organization_id,
        project_id=project_id,
        kind="onboarding",
        status="pending_brand_confirmation",
        data={"step": "brand_profile", "created_at": now.isoformat()},
    )
    session.add_all([user, organization, membership, project, brand_profile, source, subscription, Wallet(organization_id=organization_id, balance_tokens=0)])
    session.commit()
    raw_token = issue_email_token(
        session, user=user, kind="verify_email", settings=settings, request_ip=_request_ip(request)
    )
    delivered = send_account_email(user=user, kind="verify_email", raw_token=raw_token, settings=settings)
    return {
        "status": "verification_required",
        "email": email,
        "email_sent": delivered,
        "message": "Check your email to activate your private workspace.",
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    email = _normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if user.status == "pending_verification":
        raise HTTPException(403, "Email verification required")
    if user.status != "active":
        raise HTTPException(403, "Account is not active")
    membership = active_membership(session, user.id)
    if not membership:
        raise HTTPException(403, "Account has no active workspace membership")
    replacement_hash = refresh_password_hash(payload.password, user.password_hash)
    if replacement_hash:
        user.password_hash = replacement_hash
    user.last_login_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    tokens = create_session(
        session,
        user=user,
        organization_id=membership.organization_id,
        settings=settings,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {**tokens, "user": _user_payload(user, membership.organization_id, membership.data.get("role", "viewer"), tokens["default_project_id"])}


@router.post("/refresh")
def refresh(
    payload: TokenRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    tokens = rotate_session(
        session,
        raw_refresh_token=payload.token,
        settings=settings,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if not tokens:
        raise HTTPException(401, "Refresh session is invalid or expired")
    return tokens


@router.post("/logout", status_code=204)
def logout(payload: TokenRequest, session: Session = Depends(get_db)) -> None:
    record = session.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(payload.token)))
    if record and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        session.add(record)
        session.commit()


@router.post("/verify-email")
def verify_email(
    payload: TokenRequest,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    record = consume_email_token(session, payload.token, "verify_email")
    if not record or not record.user_id:
        raise HTTPException(400, "Verification link is invalid or expired")
    user = session.get(User, record.user_id)
    if not user:
        raise HTTPException(400, "Verification link is invalid or expired")
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    user.status = "active"
    session.add(user)
    session.commit()
    membership = active_membership(session, user.id)
    if not membership:
        raise HTTPException(409, "Workspace membership is missing")
    grant_signup_credit(session, membership.organization_id, user.id, settings.signup_credit_tokens)
    project = session.scalar(
        select(Resource)
        .where(
            Resource.kind == "project",
            Resource.organization_id == membership.organization_id,
            Resource.status.not_in(["deleted", "archived"]),
        )
        .order_by(Resource.created_at.asc())
    )
    if project:
        existing_analysis = session.scalar(
            select(Resource).where(
                Resource.kind == "project_analysis",
                Resource.organization_id == membership.organization_id,
                Resource.project_id == project.id,
            )
        )
        if not existing_analysis:
            analysis = Resource(
                id=f"analysis_{secrets.token_hex(12)}",
                organization_id=membership.organization_id,
                project_id=project.id,
                kind="project_analysis",
                status="queued",
                data={"website_url": project.data["website_url"], "providers": ["parallel", "google"]},
            )
            session.add(analysis)
            session.commit()
            try:
                charge_feature(
                    session,
                    organization_id=membership.organization_id,
                    user_id=user.id,
                    feature_key="project.website_analysis",
                    quantity=1,
                    reference_id=analysis.id,
                )
            except HTTPException:
                session.delete(analysis)
                session.commit()
            else:
                from .routes import _analyze_project_task

                background.add_task(
                    _analyze_project_task,
                    project_id=project.id,
                    analysis_id=analysis.id,
                    organization_id=membership.organization_id,
                    settings=settings,
                )
    tokens = create_session(
        session,
        user=user,
        organization_id=membership.organization_id,
        settings=settings,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {**tokens, "user": _user_payload(user, membership.organization_id, membership.data.get("role", "viewer"), tokens["default_project_id"])}


@router.post("/verification/resend")
def resend_verification(
    payload: EmailRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    email = _normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    if user and not user.email_verified_at:
        raw = issue_email_token(session, user=user, kind="verify_email", settings=settings, request_ip=_request_ip(request))
        send_account_email(user=user, kind="verify_email", raw_token=raw, settings=settings)
    return {"status": "accepted"}


@router.post("/password-reset/request")
def request_password_reset(
    payload: EmailRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    email = _normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    if user and user.status in {"active", "pending_verification"}:
        raw = issue_email_token(session, user=user, kind="password_reset", settings=settings, request_ip=_request_ip(request))
        send_account_email(user=user, kind="password_reset", raw_token=raw, settings=settings)
    return {"status": "accepted"}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirm,
    session: Session = Depends(get_db),
) -> dict[str, str]:
    record = consume_email_token(session, payload.token, "password_reset")
    if not record or not record.user_id:
        raise HTTPException(400, "Password reset link is invalid or expired")
    user = session.get(User, record.user_id)
    if not user:
        raise HTTPException(400, "Password reset link is invalid or expired")
    user.password_hash = hash_password(payload.password)
    user.token_version += 1
    session.add(user)
    session.commit()
    revoke_all_sessions(session, user.id)
    return {"status": "password_updated"}


@router.get("/test-support/email-token", include_in_schema=False)
def test_support_email_token(
    email: str = Query(max_length=320),
    kind: str = Query(pattern=r"^(verify_email|password_reset)$"),
    x_test_support_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if settings.app_env != "test" or not secrets.compare_digest(
        x_test_support_secret or "", settings.test_support_secret
    ):
        raise HTTPException(404, "Resource not found")
    raw = test_token(email.lower(), kind)
    if not raw:
        raise HTTPException(404, "Email token not found")
    return {"token": raw}
