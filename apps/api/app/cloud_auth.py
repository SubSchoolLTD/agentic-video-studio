from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from .config import Settings, get_settings


def require_google_service_identity(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Google service identity token required")
    if not settings.google_runtime_service_account or not settings.app_base_url:
        raise HTTPException(503, "Internal Google service identity is not configured")
    try:
        claims = id_token.verify_oauth2_token(
            token,
            GoogleAuthRequest(),
            audience=settings.app_base_url,
        )
    except Exception as exc:
        raise HTTPException(401, "Invalid Google service identity token") from exc
    if claims.get("email") != settings.google_runtime_service_account or not claims.get("email_verified"):
        raise HTTPException(403, "Unexpected Google service identity")
    return claims


def require_internal_service_identity(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Accept the OVH scheduler token, with Google OIDC retained during cutover."""
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if settings.internal_automation_token:
        if scheme.lower() == "bearer" and token and hmac.compare_digest(
            token,
            settings.internal_automation_token,
        ):
            return {"email": "framewise-scheduler@local", "email_verified": True, "provider": "local"}
        raise HTTPException(401, "Internal service identity token required")
    return require_google_service_identity(request, settings)
