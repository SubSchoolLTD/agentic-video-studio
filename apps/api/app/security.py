from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import active_membership, decode_access_token
from .config import Settings, get_settings
from .database import get_db
from .models import Resource, User
from .repository import find_api_key

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor_id: str
    organization_id: str
    project_id: str | None
    role: str
    scopes: frozenset[str]
    email: str | None = None
    display_name: str | None = None
    is_platform_admin: bool = False
    project_scope: frozenset[str] | None = None

    def require(self, scope: str) -> None:
        if "admin" not in self.scopes and scope not in self.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")

    def require_platform_admin(self) -> None:
        if not self.is_platform_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform administrator access required")

    def can_access_project(self, project_id: str | None) -> bool:
        return project_id is None or self.project_scope is None or project_id in self.project_scope


ALL_SCOPES = frozenset(
    {
        "admin",
        "projects:read",
        "projects:write",
        "sources:read",
        "sources:write",
        "research:read",
        "research:run",
        "generations:read",
        "generations:write",
        "videos:read",
        "videos:approve",
        "publications:read",
        "publications:write",
        "analytics:read",
        "analytics:write",
        "integrations:read",
        "integrations:write",
        "webhooks:write",
    }
)

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": ALL_SCOPES,
    "admin": ALL_SCOPES,
    "editor": frozenset(scope for scope in ALL_SCOPES if scope != "admin" and not scope.startswith("integrations:")),
    "publisher": frozenset(
        {"projects:read", "generations:read", "videos:read", "videos:approve", "publications:read", "publications:write", "analytics:read"}
    ),
    "analyst": frozenset({"projects:read", "sources:read", "research:read", "generations:read", "videos:read", "publications:read", "analytics:read"}),
    "viewer": frozenset({"projects:read", "sources:read", "research:read", "generations:read", "videos:read", "publications:read", "analytics:read"}),
}


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_organization_id: str | None = Header(default=None),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    token = credentials.credentials
    if settings.app_auth_mode == "demo" and token == settings.app_demo_token:
        organization_id = "org_demo"
        if x_organization_id and x_organization_id != organization_id:
            membership = session.scalar(
                select(Resource).where(
                    Resource.kind == "membership",
                    Resource.organization_id == x_organization_id,
                    Resource.data["actor_id"].as_string() == "user_demo_owner",
                    Resource.status == "active",
                )
            )
            if not membership:
                # Hide tenant existence just like a resource-level authorization guard.
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
            organization_id = x_organization_id
        return Principal(
            actor_id="user_demo_owner",
            organization_id=organization_id,
            project_id=None,
            role="owner",
            scopes=ALL_SCOPES,
            email="demo@example.invalid",
            display_name="Demo User",
            is_platform_admin=True,
        )
    if settings.app_auth_mode == "jwt":
        try:
            claims = decode_access_token(token, settings)
        except jwt.PyJWTError:
            claims = None
        if claims:
            user = session.get(User, str(claims["sub"]))
            if not user or user.status != "active" or user.email_verified_at is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is not active")
            if int(claims.get("ver", 0)) != user.token_version:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
            organization_id = x_organization_id or str(claims["org"])
            membership = active_membership(session, user.id, organization_id)
            if not membership:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
            role = str(membership.data.get("role") or "viewer")
            raw_scope = membership.data.get("project_scope") or ["*"]
            project_scope = None if "*" in raw_scope else frozenset(str(item) for item in raw_scope)
            return Principal(
                actor_id=user.id,
                organization_id=organization_id,
                project_id=next(iter(project_scope)) if project_scope and len(project_scope) == 1 else None,
                role=role,
                scopes=ROLE_SCOPES.get(role, ROLE_SCOPES["viewer"]),
                email=user.email,
                display_name=user.display_name,
                is_platform_admin=bool(user.is_platform_admin),
                project_scope=project_scope,
            )
    record = find_api_key(session, token, settings.api_key_pepper)
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return Principal(
        actor_id=record.id,
        organization_id=record.organization_id,
        project_id=record.project_id,
        role="service_account",
        scopes=frozenset(scope for scope in record.scopes.split(" ") if scope),
        project_scope=frozenset({record.project_id}),
    )


def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute http/https URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in URLs are not allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local network URLs are not allowed")

    addresses: set[str] = set()
    try:
        addresses.add(str(ipaddress.ip_address(host)))
    except ValueError:
        if resolve_dns:
            try:
                addresses.update(item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443))
            except socket.gaierror as exc:
                raise ValueError("URL hostname could not be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Private, reserved, loopback, or metadata network targets are blocked")
        if str(ip) in {"169.254.169.254", "metadata.google.internal"}:
            raise ValueError("Cloud metadata targets are blocked")
    return parsed.geturl()
