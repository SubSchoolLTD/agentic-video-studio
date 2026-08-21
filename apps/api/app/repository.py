from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .models import ApiKeyRecord, IdempotencyRecord, Resource


class ConflictError(Exception):
    pass


class ResourceRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(8)}"

    def add(
        self,
        *,
        kind: str,
        organization_id: str,
        project_id: str | None,
        data: dict[str, Any],
        status: str = "active",
        resource_id: str | None = None,
        version: int = 1,
    ) -> Resource:
        resource = Resource(
            id=resource_id or self.new_id(kind[:5]),
            kind=kind,
            organization_id=organization_id,
            project_id=project_id,
            data=data,
            status=status,
            version=version,
        )
        self.session.add(resource)
        self.session.commit()
        self.session.refresh(resource)
        return resource

    def get(
        self,
        resource_id: str,
        *,
        organization_id: str,
        kind: str | None = None,
        project_id: str | None = None,
    ) -> Resource | None:
        statement = select(Resource).where(
            Resource.id == resource_id,
            Resource.organization_id == organization_id,
        )
        if kind:
            statement = statement.where(Resource.kind == kind)
        if project_id:
            statement = statement.where(Resource.project_id == project_id)
        return self.session.scalar(statement)

    def get_any(self, resource_id: str, *, kind: str | None = None) -> Resource | None:
        statement = select(Resource).where(Resource.id == resource_id)
        if kind:
            statement = statement.where(Resource.kind == kind)
        return self.session.scalar(statement)

    def list(
        self,
        *,
        organization_id: str,
        kind: str,
        project_id: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        statement: Select[tuple[Resource]] = select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.kind == kind,
        )
        if project_id:
            statement = statement.where(Resource.project_id == project_id)
        if statuses:
            statement = statement.where(Resource.status.in_(list(statuses)))
        statement = statement.order_by(Resource.created_at.desc()).limit(min(limit, 200))
        return list(self.session.scalars(statement))

    def update(
        self,
        resource: Resource,
        *,
        data: dict[str, Any] | None = None,
        status: str | None = None,
        merge: bool = True,
        increment_version: bool = False,
    ) -> Resource:
        if data is not None:
            resource.data = {**resource.data, **data} if merge else data
        if status is not None:
            resource.status = status
        if increment_version:
            resource.version += 1
        resource.updated_at = datetime.now(UTC)
        self.session.add(resource)
        self.session.commit()
        self.session.refresh(resource)
        return resource

    @staticmethod
    def serialize(resource: Resource) -> dict[str, Any]:
        payload = {
            **resource.data,
            "id": resource.id,
            "kind": resource.kind,
            "organization_id": resource.organization_id,
            "project_id": resource.project_id,
            "status": resource.status,
            "version": resource.version,
            "created_at": resource.created_at.isoformat(),
            "updated_at": resource.updated_at.isoformat(),
        }
        if resource.kind == "connection":
            payload.pop("secret_ref", None)
            payload.pop("pending_page_url", None)
        if resource.kind == "video_version" and payload.get("render_url"):
            from .config import get_settings
            from .storage import MediaStorage

            payload["render_url"] = MediaStorage(get_settings()).signed_path(
                str(payload["render_url"]), resource.organization_id
            )
        if resource.kind == "character" and payload.get("reference_url"):
            from .config import get_settings
            from .storage import MediaStorage

            payload["reference_url"] = MediaStorage(get_settings()).signed_path(
                str(payload["reference_url"]), resource.organization_id
            )
        if resource.kind == "publication" and payload.get("export_package_url"):
            from .config import get_settings
            from .storage import MediaStorage

            payload["export_package_url"] = MediaStorage(get_settings()).signed_path(
                str(payload["export_package_url"]), resource.organization_id
            )
        return payload


def canonical_request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_idempotent_response(
    session: Session,
    *,
    actor_id: str,
    endpoint: str,
    key: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]] | None:
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if not record:
        return None
    if record.request_hash != canonical_request_hash(payload):
        raise ConflictError("The Idempotency-Key was already used with a different request body.")
    return record.status_code, record.response_json


def save_idempotent_response(
    session: Session,
    *,
    actor_id: str,
    endpoint: str,
    key: str,
    payload: dict[str, Any],
    status_code: int,
    response: dict[str, Any],
) -> None:
    session.add(
        IdempotencyRecord(
            actor_id=actor_id,
            endpoint=endpoint,
            idempotency_key=key,
            request_hash=canonical_request_hash(payload),
            status_code=status_code,
            response_json=response,
        )
    )
    session.commit()


def hash_api_key(raw_key: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{raw_key}".encode()).hexdigest()


def find_api_key(session: Session, raw_key: str, pepper: str) -> ApiKeyRecord | None:
    prefix = raw_key[:18]
    record = session.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_prefix == prefix))
    if not record or record.revoked_at is not None:
        return None
    if not secrets.compare_digest(record.key_hash, hash_api_key(raw_key, pepper)):
        return None
    if record.expires_at and record.expires_at < datetime.now(UTC):
        return None
    record.last_used_at = datetime.now(UTC)
    session.add(record)
    session.commit()
    return record
