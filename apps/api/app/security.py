from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .repository import find_api_key

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor_id: str
    organization_id: str
    project_id: str | None
    role: str
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if "admin" not in self.scopes and scope not in self.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")


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
        return Principal(
            actor_id="user_demo_owner",
            organization_id=x_organization_id or "org_demo",
            project_id=None,
            role="owner",
            scopes=ALL_SCOPES,
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
