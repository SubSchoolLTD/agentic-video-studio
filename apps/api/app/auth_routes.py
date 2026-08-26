from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
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
from .billing import add_ledger_entry
from .config import Settings, get_settings
from .database import get_db
from .email_service import consume_email_token, issue_email_token, send_account_email, test_token
from .models import AuthIdentity, AuthSession, Resource, User, Wallet
from .security import validate_public_url
from .strategy_defaults import cold_start_strategy

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=2, max_length=160)
    organization_name: str | None = Field(default=None, min_length=2, max_length=120)
    project_name: str | None = Field(default=None, min_length=2, max_length=120)
    website_url: HttpUrl | None = None
    default_language: str = Field(default="en", min_length=2, max_length=12)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=100, max_length=10_000)


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetConfirm(TokenRequest):
    password: str = Field(min_length=10, max_length=128)


class TestSupportAdminRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class TestSupportBalanceRequest(TestSupportAdminRequest):
    amount_cents: int = Field(default=100_000, ge=1, le=10_000_000)


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


def _onboarding_complete(session: Session, project_id: str | None) -> bool:
    if not project_id:
        return False
    onboarding = session.scalar(
        select(Resource)
        .where(Resource.kind == "onboarding", Resource.project_id == project_id)
        .order_by(Resource.created_at.desc())
    )
    # Projects created before the onboarding flow are already usable and must not be
    # unexpectedly redirected when the new flow is deployed.
    return onboarding is None or onboarding.status == "completed"


def _user_payload(
    session: Session, user: User, organization_id: str, role: str, project_id: str | None
) -> dict[str, object]:
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
        "onboarding_complete": _onboarding_complete(session, project_id),
    }


def _provision_workspace(
    session: Session,
    *,
    user: User,
    organization_name: str | None = None,
    project_name: str | None = None,
    website_url: str | None = None,
    default_language: str = "en",
    timezone: str = "UTC",
) -> tuple[str, str]:
    organization_id = f"org_{secrets.token_hex(12)}"
    project_id = f"prj_{secrets.token_hex(12)}"
    resolved_org_name = (organization_name or f"{user.display_name}'s workspace").strip()
    resolved_project_name = (project_name or "My project").strip()
    org_slug = _slug(resolved_org_name)
    if session.scalar(
        select(Resource).where(Resource.kind == "organization", Resource.data["slug"].as_string() == org_slug)
    ):
        org_slug = f"{org_slug[:47]}-{secrets.token_hex(4)}"
    now = datetime.now(UTC)
    project_data = {
        "name": resolved_project_name,
        "slug": _slug(resolved_project_name),
        "website_url": website_url or "",
        "default_language": default_language,
        "regions": [],
        "timezone": timezone,
        "automation_mode": "off",
        "autopilot_paused": False,
        "rights_confirmed": True,
        "brand_profile_version": 1,
        "settings": {
            "research": {"backlog_target": 150, "recency_days": 30, "max_candidates": 50},
            "content_mix": {"selling": 20, "viral": 30, "informative": 50},
            "video_defaults": {
                mode: {"audio_mode": "veo_native", "native_voice_preset": "warm_conversational", "continue_scenes": mode == "ugc_creator"}
                for mode in ("ugc_creator", "storytelling", "cinematic", "motion_graphics")
            },
        },
    }
    starter_profile = {
        "identity": {
            "name": resolved_project_name,
            "website": website_url or "",
            "description": "Website analysis is waiting for onboarding.",
            "languages": [default_language],
            "regions": [],
        },
        "audiences": {"primary": [], "secondary": []},
        "value_propositions": [],
        "tone": {"traits": ["clear", "credible"], "prohibited_traits": ["misleading", "guaranteed outcomes"]},
        "claims": {"allowed": [], "require_source": ["performance and outcome claims"], "prohibited": []},
        "visual": {"palette": [], "logo_assets": [], "fonts": [], "references": [], "forbidden_styles": []},
        "cta": {"primary": "Learn more", "alternatives": [], "target_urls": [website_url] if website_url else []},
        "compliance": {"high_risk_topics": [], "mandatory_disclosures": ["Synthetic media where required"]},
        "source_policy": {"trusted_domains": [], "blocked_domains": [], "max_source_age_days": 90},
        "project_context": {},
        "confirmed": False,
        "confidence": 0.1,
    }
    resources = [
        Resource(
            id=organization_id, organization_id=organization_id, project_id=None, kind="organization", status="active",
            data={"name": resolved_org_name, "slug": org_slug, "timezone": timezone, "owner_actor_id": user.id},
        ),
        Resource(
            id=f"mem_{secrets.token_hex(12)}", organization_id=organization_id, project_id=None,
            kind="membership", status="active", data={"actor_id": user.id, "role": "owner", "project_scope": ["*"]},
        ),
        Resource(id=project_id, organization_id=organization_id, project_id=project_id, kind="project", status="active", data=project_data),
        Resource(
            id=f"brand_{secrets.token_hex(12)}", organization_id=organization_id, project_id=project_id,
            kind="brand_profile", status="review_required", data=starter_profile,
        ),
        Resource(
            id=f"onb_{secrets.token_hex(12)}", organization_id=organization_id, project_id=project_id,
            kind="onboarding", status="pending", data={"step": "website", "created_at": now.isoformat()},
        ),
        Resource(
            id=f"strategy_{secrets.token_hex(12)}", organization_id=organization_id, project_id=project_id,
            kind="strategy", status="active", data=cold_start_strategy(),
        ),
    ]
    if website_url:
        resources.append(
            Resource(
                id=f"src_{secrets.token_hex(12)}", organization_id=organization_id, project_id=project_id,
                kind="source", status="healthy", data={
                    "type": "website", "name": f"{resolved_project_name} website", "url": website_url,
                    "trust_level": "owned", "generation_policy": "research_then_approval",
                },
            )
        )
    session.add_all([*resources, Wallet(organization_id=organization_id, balance_cents=0)])
    session.commit()
    return organization_id, project_id


@router.post("/register", status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    email = _normalize_email(payload.email)
    if payload.website_url:
        try:
            validate_public_url(str(payload.website_url), resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user_id = f"usr_{secrets.token_hex(12)}"
    user = User(
        id=user_id,
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        status="pending_verification",
    )
    session.add(user)
    session.commit()
    _, project_id = _provision_workspace(
        session,
        user=user,
        organization_name=payload.organization_name,
        project_name=payload.project_name,
        website_url=str(payload.website_url) if payload.website_url else None,
        default_language=payload.default_language,
        timezone=payload.timezone,
    )
    # Legacy clients supplied the whole project at registration. Treat their one-step
    # setup as complete while the new UI continues into the dedicated onboarding flow.
    if payload.organization_name and payload.project_name and payload.website_url:
        onboarding = session.scalar(select(Resource).where(Resource.kind == "onboarding", Resource.project_id == project_id))
        project = session.get(Resource, project_id)
        if project:
            settings_data = dict(project.data.get("settings") or {})
            settings_data["video_defaults"] = {
                mode: {"audio_mode": "google_tts", "native_voice_preset": "warm_conversational", "continue_scenes": mode == "ugc_creator"}
                for mode in ("ugc_creator", "storytelling", "cinematic", "motion_graphics")
            }
            project.data = {**project.data, "settings": settings_data}
            session.add(project)
        if onboarding:
            onboarding.status = "completed"
            onboarding.data = {**onboarding.data, "step": "complete", "completed_at": datetime.now(UTC).isoformat()}
            session.add(onboarding)
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
    return {**tokens, "user": _user_payload(session, user, membership.organization_id, membership.data.get("role", "viewer"), tokens["default_project_id"])}


@router.post("/google")
def google_login(
    payload: GoogleLoginRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.google_oauth_client_id:
        raise HTTPException(503, "Google sign-in is not configured")
    try:
        claims = google_id_token.verify_oauth2_token(
            payload.credential,
            GoogleAuthRequest(),
            audience=settings.google_oauth_client_id,
        )
    except Exception as exc:
        raise HTTPException(401, "Google sign-in token is invalid or expired") from exc
    if not claims.get("email_verified") or not claims.get("sub") or not claims.get("email"):
        raise HTTPException(401, "Google did not return a verified email")
    email = _normalize_email(str(claims["email"]))
    subject = str(claims["sub"])
    identity = session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google", AuthIdentity.provider_subject == subject
        )
    )
    user = session.get(User, identity.user_id) if identity else None
    if not user:
        user = session.scalar(select(User).where(User.email == email))
        if not user:
            display_name = str(claims.get("name") or email.split("@", 1)[0]).strip()[:160]
            user = User(
                id=f"usr_{secrets.token_hex(12)}",
                email=email,
                # A Google-only account has no usable local password until the owner
                # explicitly completes the password-reset flow.
                password_hash=hash_password(secrets.token_urlsafe(48)),
                display_name=display_name,
                status="active",
                email_verified_at=datetime.now(UTC),
            )
            session.add(user)
            session.commit()
            _provision_workspace(session, user=user)
        if not identity:
            identity = AuthIdentity(
                id=f"aid_{secrets.token_hex(12)}",
                user_id=user.id,
                provider="google",
                provider_subject=subject,
                provider_email=email,
            )
            session.add(identity)
    if user.email != email:
        raise HTTPException(409, "This Google identity is already linked to another account")
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    if user.status == "pending_verification":
        user.status = "active"
    if user.status != "active":
        raise HTTPException(403, "Account is not active")
    user.last_login_at = datetime.now(UTC)
    identity.last_used_at = datetime.now(UTC)
    session.add_all([user, identity])
    session.commit()
    membership = active_membership(session, user.id)
    if not membership:
        raise HTTPException(409, "Workspace membership is missing")
    tokens = create_session(
        session,
        user=user,
        organization_id=membership.organization_id,
        settings=settings,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {
        **tokens,
        "user": _user_payload(
            session, user, membership.organization_id, membership.data.get("role", "viewer"), tokens["default_project_id"]
        ),
    }


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
    tokens = create_session(
        session,
        user=user,
        organization_id=membership.organization_id,
        settings=settings,
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return {**tokens, "user": _user_payload(session, user, membership.organization_id, membership.data.get("role", "viewer"), tokens["default_project_id"])}


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


@router.post("/test-support/platform-admin", include_in_schema=False)
def test_support_platform_admin(
    payload: TestSupportAdminRequest,
    x_test_support_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    if settings.app_env != "test" or not secrets.compare_digest(
        x_test_support_secret or "", settings.test_support_secret
    ):
        raise HTTPException(404, "Resource not found")
    user = session.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or user.status != "active":
        raise HTTPException(404, "Active user not found")
    user.is_platform_admin = True
    session.add(user)
    session.commit()
    return {"user_id": user.id, "status": "platform_admin"}


@router.post("/test-support/balance", include_in_schema=False)
def test_support_balance(
    payload: TestSupportBalanceRequest,
    x_test_support_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> dict[str, int | str]:
    if settings.app_env != "test" or not secrets.compare_digest(
        x_test_support_secret or "", settings.test_support_secret
    ):
        raise HTTPException(404, "Resource not found")
    user = session.scalar(select(User).where(User.email == payload.email.lower()))
    membership = active_membership(session, user.id) if user else None
    if not user or not membership:
        raise HTTPException(404, "Active user not found")
    add_ledger_entry(
        session,
        organization_id=membership.organization_id,
        user_id=user.id,
        amount_cents=payload.amount_cents,
        event_type="test_fixture",
        description="E2E balance fixture",
        reference_id="test-support",
    )
    return {"status": "credited", "amount_cents": payload.amount_cents}
