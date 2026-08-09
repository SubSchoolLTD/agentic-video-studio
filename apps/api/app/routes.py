from __future__ import annotations

import asyncio
import difflib
import fnmatch
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import feedparser
import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .cloud_auth import require_google_service_identity
from .config import Settings, get_settings
from .database import SessionLocal, get_db
from .events import EventSink
from .ingestion import extract_article, fetch_public_text, prompt_injection_score
from .metrics import collect_youtube_metrics, mock_youtube_metrics, observed_performance
from .models import ApiKeyRecord, Resource
from .providers import ParallelSearchProvider
from .publishing import (
    PROVIDER_CAPABILITIES,
    confirmation_token,
    create_export_package,
    exchange_youtube_code,
    get_youtube_video_status,
    resolve_youtube_channel,
    store_oauth_secret,
    upload_youtube_video,
    youtube_authorization_url,
)
from .repository import (
    ConflictError,
    ResourceRepository,
    get_idempotent_response,
    hash_api_key,
    save_idempotent_response,
)
from .schemas import (
    ApiKeyCreate,
    BrandProfilePatch,
    ContentItemCreate,
    ConversionEventCreate,
    GenerationCreate,
    IdeaCreate,
    OrganizationCreate,
    ProjectCreate,
    ProjectPatch,
    PublicationConfirm,
    PublicationCreate,
    ResearchProfileCreate,
    ResearchRunCreate,
    ReviewAction,
    SceneRegenerate,
    ScoreOverride,
    ScriptPatch,
    SourceCreate,
    SourceItemCreate,
    SourcePatch,
    TopicMute,
    WebhookCreate,
    WebhookPatch,
)
from .security import ALL_SCOPES, Principal, get_principal, validate_public_url
from .seed import SUBSCHOOL_BRAND
from .storage import MediaStorage
from .workflow import WorkflowManager, initial_stage_state

router = APIRouter(prefix="/v1")


def get_workflow(request: Request) -> WorkflowManager:
    return request.app.state.workflow


def serialize_many(resources: list[Resource]) -> dict[str, Any]:
    return {"items": [ResourceRepository.serialize(item) for item in resources], "next_cursor": None}


def require_resource(
    repo: ResourceRepository,
    resource_id: str,
    principal: Principal,
    *,
    kind: str | None = None,
    project_id: str | None = None,
) -> Resource:
    resource = repo.get(
        resource_id,
        organization_id=principal.organization_id,
        kind=kind,
        project_id=project_id,
    )
    if not resource or (principal.project_id and resource.project_id not in {None, principal.project_id}):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource


def require_project(repo: ResourceRepository, project_id: str, principal: Principal) -> Resource:
    return require_resource(repo, project_id, principal, kind="project", project_id=project_id)


def serialize_video(repo: ResourceRepository, video: Resource, *, organization_id: str) -> dict[str, Any]:
    """Hydrate mutable review state while preserving immutable render metadata."""
    payload = ResourceRepository.serialize(video)
    versions = []
    for snapshot in video.data.get("versions", []):
        version = repo.get(snapshot["id"], organization_id=organization_id, kind="video_version")
        versions.append(ResourceRepository.serialize(version) if version else snapshot)
    payload["versions"] = versions
    return payload


@router.get("/health", tags=["system"])
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agentic-video-studio-api",
        "environment": settings.app_env,
        "provider_mode": settings.provider_mode,
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/me", tags=["auth"])
def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {
        "actor_id": principal.actor_id,
        "organization_id": principal.organization_id,
        "project_id": principal.project_id,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
    }


@router.get("/organizations/current", tags=["organizations"])
def current_organization(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_db)
) -> dict[str, Any]:
    resource = require_resource(ResourceRepository(session), principal.organization_id, principal, kind="organization")
    return ResourceRepository.serialize(resource)


@router.post("/organizations", status_code=201, tags=["organizations"])
def create_organization(
    payload: OrganizationCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("admin")
    body = payload.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = get_idempotent_response(
                session,
                actor_id=principal.actor_id,
                endpoint="POST:/v1/organizations",
                key=idempotency_key,
                payload=body,
            )
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        if cached:
            return cached[1]
    repo = ResourceRepository(session)
    slug = payload.slug or "-".join(payload.name.lower().split())[:80]
    existing = session.scalar(
        select(Resource).where(Resource.kind == "organization", Resource.data["slug"].as_string() == slug)
    )
    if existing:
        raise HTTPException(409, "Organization slug is already in use")
    organization_id = ResourceRepository.new_id("org")
    organization = repo.add(
        resource_id=organization_id,
        kind="organization",
        organization_id=organization_id,
        project_id=None,
        status="active",
        data={
            **body,
            "slug": slug,
            "owner_actor_id": principal.actor_id,
        },
    )
    membership = repo.add(
        kind="membership",
        organization_id=organization_id,
        project_id=None,
        status="active",
        data={"actor_id": principal.actor_id, "role": "owner", "project_scope": ["*"]},
    )
    response = {
        "organization": ResourceRepository.serialize(organization),
        "membership": ResourceRepository.serialize(membership),
    }
    if idempotency_key:
        save_idempotent_response(
            session,
            actor_id=principal.actor_id,
            endpoint="POST:/v1/organizations",
            key=idempotency_key,
            payload=body,
            status_code=201,
            response=response,
        )
    return response


@router.post("/projects", status_code=status.HTTP_202_ACCEPTED, tags=["projects"])
def create_project(
    payload: ProjectCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    body = payload.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = get_idempotent_response(
                session, actor_id=principal.actor_id, endpoint="POST:/v1/projects", key=idempotency_key, payload=body
            )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if cached:
            return cached[1]
    try:
        validate_public_url(str(payload.website_url), resolve_dns=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo = ResourceRepository(session)
    slug = "-".join(payload.name.lower().split())[:64]
    project = repo.add(
        kind="project",
        organization_id=principal.organization_id,
        project_id=None,
        status="analyzing" if payload.analyze_website else "draft",
        data={
            "name": payload.name,
            "slug": slug,
            "website_url": str(payload.website_url),
            "default_language": payload.default_language,
            "regions": payload.regions,
            "timezone": payload.timezone,
            "automation_mode": "manual",
            "autopilot_paused": False,
            "rights_confirmed": payload.rights_confirmed,
            "brief": payload.brief,
            "settings": {},
        },
    )
    project.project_id = project.id
    session.add(project)
    session.commit()
    analysis = repo.add(
        kind="project_analysis",
        organization_id=principal.organization_id,
        project_id=project.id,
        status="queued",
        data={"website_url": str(payload.website_url), "provider": "parallel"},
    )
    response = {
        "project_id": project.id,
        "status": project.status,
        "analysis_job_id": analysis.id,
        "links": {"self": f"/v1/projects/{project.id}", "job": f"/v1/project-analyses/{analysis.id}"},
    }
    if idempotency_key:
        save_idempotent_response(
            session,
            actor_id=principal.actor_id,
            endpoint="POST:/v1/projects",
            key=idempotency_key,
            payload=body,
            status_code=202,
            response=response,
        )
    return response


@router.get("/projects", tags=["projects"])
def list_projects(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_db)
) -> dict[str, Any]:
    principal.require("projects:read")
    items = ResourceRepository(session).list(
        organization_id=principal.organization_id, kind="project", project_id=principal.project_id
    )
    return serialize_many(items)


@router.get("/projects/{project_id}", tags=["projects"])
def get_project(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:read")
    return ResourceRepository.serialize(require_project(ResourceRepository(session), project_id, principal))


@router.patch("/projects/{project_id}", tags=["projects"])
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    changes = payload.model_dump(exclude_none=True)
    if "settings" in changes:
        scoring = dict(changes["settings"].get("scoring") or {})
        system_minimums = {
            "readiness_manual": 70,
            "readiness_autopublish": 85,
            "confidence": 0.6,
        }
        below_minimum = {
            key: {"requested": scoring[key], "minimum": minimum}
            for key, minimum in system_minimums.items()
            if key in scoring and float(scoring[key]) < minimum
        }
        if below_minimum:
            raise HTTPException(
                422,
                {"message": "Scoring thresholds cannot be below system safety minimums", "fields": below_minimum},
            )
        merged_settings = dict(project.data.get("settings", {}))
        for section, value in changes["settings"].items():
            if isinstance(value, dict) and isinstance(merged_settings.get(section), dict):
                merged_settings[section] = {**merged_settings[section], **value}
            else:
                merged_settings[section] = value
        changes["settings"] = merged_settings
    return ResourceRepository.serialize(repo.update(project, data=changes))


async def _analyze_project_task(
    *, project_id: str, analysis_id: str, organization_id: str, settings: Settings
) -> None:
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        project = repo.get_any(project_id, kind="project")
        analysis = repo.get_any(analysis_id, kind="project_analysis")
        if not project or not analysis:
            return
        repo.update(analysis, status="running", data={"started_at": datetime.now(UTC).isoformat()})
        try:
            packet = await ParallelSearchProvider(settings).search(
                f"Analyze the public identity, audience, products, claims, and external context of {project.data['website_url']}"
            )
            profile = {
                **SUBSCHOOL_BRAND,
                "identity": {
                    **SUBSCHOOL_BRAND["identity"],
                    "name": project.data["name"],
                    "website": project.data["website_url"],
                },
                "confirmed": False,
                "confidence": 0.78,
                "source_ids": [source["id"] for source in packet.sources],
            }
            brand = repo.add(
                kind="brand_profile",
                organization_id=organization_id,
                project_id=project_id,
                status="review_required",
                data=profile,
            )
            repo.update(
                analysis,
                status="completed",
                data={"brand_profile_id": brand.id, "parallel_request_ids": [packet.request_id], "sources": packet.sources},
            )
            repo.update(project, status="review_required", data={"brand_profile_version": 1})
        except Exception as exc:
            repo.update(analysis, status="failed", data={"error": str(exc), "retryable": True})


@router.post("/projects/{project_id}/analyze-website", status_code=202, tags=["projects"])
def analyze_website(
    project_id: str,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    analysis = repo.add(
        kind="project_analysis",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="queued",
        data={"website_url": project.data["website_url"], "provider": "parallel"},
    )
    background.add_task(
        _analyze_project_task,
        project_id=project_id,
        analysis_id=analysis.id,
        organization_id=principal.organization_id,
        settings=settings,
    )
    return {"job_id": analysis.id, "status": "queued", "status_url": f"/v1/project-analyses/{analysis.id}"}


@router.get("/project-analyses/{analysis_id}", tags=["projects"])
def get_analysis(
    analysis_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), analysis_id, principal, kind="project_analysis")
    )


@router.get("/projects/{project_id}/brand-profile", tags=["projects"])
def get_brand_profile(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(ResourceRepository(session), project_id, principal)
    resource = session.scalar(
        select(Resource)
        .where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == project_id,
            Resource.kind == "brand_profile",
        )
        .order_by(Resource.version.desc())
    )
    if not resource:
        raise HTTPException(404, "Brand profile not found")
    return ResourceRepository.serialize(resource)


@router.patch("/projects/{project_id}/brand-profile", tags=["projects"])
def patch_brand_profile(
    project_id: str,
    payload: BrandProfilePatch,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    existing = session.scalar(
        select(Resource)
        .where(Resource.organization_id == principal.organization_id, Resource.project_id == project_id, Resource.kind == "brand_profile")
        .order_by(Resource.version.desc())
    )
    data = {**(existing.data if existing else {}), **payload.model_dump(exclude_none=True)}
    version = (existing.version + 1) if existing else 1
    profile = repo.add(
        kind="brand_profile",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="confirmed" if payload.confirmed else "review_required",
        version=version,
        data=data,
    )
    repo.update(project, data={"brand_profile_version": version})
    return ResourceRepository.serialize(profile)


@router.post("/projects/{project_id}/activate", tags=["projects"])
def activate_project(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    brand = session.scalar(
        select(Resource).where(Resource.project_id == project_id, Resource.kind == "brand_profile", Resource.status == "confirmed")
    )
    if not brand:
        raise HTTPException(409, "Project brand profile must be confirmed before activation")
    brief = project.data.get("brief") or {}
    missing = [field for field in ("audience", "objective", "policy_defaults") if not brief.get(field)]
    if not project.data.get("default_language"):
        missing.append("default_language")
    has_input = session.scalar(
        select(Resource.id).where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == project_id,
            Resource.kind.in_(("source", "source_item", "idea")),
            Resource.status.not_in(("deleted", "rejected")),
        )
    )
    if not has_input:
        missing.append("source_or_manual_idea")
    if missing:
        raise HTTPException(409, {"message": "Project brief is incomplete", "missing_fields": missing})
    return ResourceRepository.serialize(repo.update(project, status="active"))


@router.post("/projects/{project_id}/pause", tags=["projects"])
def pause_project(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    return ResourceRepository.serialize(repo.update(project, status="paused", data={"autopilot_paused": True}))


@router.post("/projects/{project_id}/resume", tags=["projects"])
def resume_project(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    return ResourceRepository.serialize(repo.update(project, status="active", data={"autopilot_paused": False}))


@router.post("/projects/{project_id}/sources", status_code=201, tags=["sources"])
def create_source(
    project_id: str,
    payload: SourceCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    if payload.url:
        try:
            validate_public_url(str(payload.url), resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    source = repo.add(
        kind="source",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="healthy",
        data={
            **payload.model_dump(mode="json"),
            "trust_level": "owned" if payload.type in {"website", "api", "manual"} else "review",
            "last_checked": None,
            "generation_policy": payload.config.get("generation_policy", "research_then_approval"),
        },
    )
    return ResourceRepository.serialize(source)


@router.get("/projects/{project_id}/sources", tags=["sources"])
def list_sources(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="source"
        )
    )


@router.patch("/sources/{source_id}", tags=["sources"])
def patch_source(
    source_id: str,
    payload: SourcePatch,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    source = require_resource(repo, source_id, principal, kind="source")
    changes = payload.model_dump(mode="json", exclude_none=True)
    status_value = changes.pop("status", None)
    if "url" in changes:
        try:
            validate_public_url(str(changes["url"]), resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if "config" in changes:
        changes["config"] = {**dict(source.data.get("config") or {}), **dict(changes["config"])}
    return ResourceRepository.serialize(repo.update(source, status=status_value, data=changes))


@router.delete("/sources/{source_id}", status_code=204, tags=["sources"])
def delete_source(
    source_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> Response:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    source = require_resource(repo, source_id, principal, kind="source")
    repo.update(
        source,
        status="deleted",
        data={"deleted_at": datetime.now(UTC).isoformat(), "deleted_by": principal.actor_id},
    )
    return Response(status_code=204)


def _source_fingerprint(payload: dict[str, Any]) -> str:
    canonical = "|".join(
        [
            str(payload.get("external_id") or ""),
            str(payload.get("canonical_url") or ""),
            str(payload.get("title") or ""),
            str(payload.get("content_markdown") or ""),
        ]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _semantic_source_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    def normalized(value: dict[str, Any]) -> str:
        text = f"{value.get('title', '')} {value.get('content_markdown', '')}".lower()
        return " ".join("".join(character if character.isalnum() else " " for character in text).split())[:20_000]

    return difflib.SequenceMatcher(None, normalized(left), normalized(right), autojunk=False).ratio()


def _create_source_item(
    *,
    project_id: str,
    body: dict[str, Any],
    principal: Principal,
    session: Session,
    idempotency_key: str | None,
    endpoint: str,
) -> tuple[Resource, bool]:
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    if body.get("canonical_url"):
        try:
            validate_public_url(str(body["canonical_url"]), resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if not body.get("rights_confirmed"):
        raise HTTPException(422, "Rights confirmation is required for source ingestion")
    if idempotency_key:
        try:
            cached = get_idempotent_response(
                session, actor_id=principal.actor_id, endpoint=endpoint, key=idempotency_key, payload=body
            )
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        if cached:
            resource = repo.get(cached[1]["source_item_id"], organization_id=principal.organization_id, kind="source_item")
            if resource:
                return resource, True
    content_hash = _source_fingerprint(body)
    duplicate_conditions = [Resource.data["content_hash"].as_string() == content_hash]
    if body.get("external_id"):
        duplicate_conditions.append(Resource.data["external_id"].as_string() == str(body["external_id"]))
    if body.get("canonical_url"):
        duplicate_conditions.append(Resource.data["canonical_url"].as_string() == str(body["canonical_url"]))
    duplicate = session.scalar(
        select(Resource).where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == project_id,
            Resource.kind == "source_item",
            or_(*duplicate_conditions),
        )
    )
    if duplicate:
        return duplicate, True
    metadata = dict(body.get("metadata") or {})
    metadata.setdefault("prompt_injection_score", prompt_injection_score(str(body.get("content_markdown") or "")))
    metadata.setdefault("retrieved_content_is_data", True)
    normalized_body = {**body, "metadata": metadata}
    possible_duplicate_of = None
    duplicate_similarity = 0.0
    for existing in repo.list(
        organization_id=principal.organization_id,
        project_id=project_id,
        kind="source_item",
        limit=100,
    ):
        similarity = _semantic_source_similarity(normalized_body, existing.data)
        if similarity > duplicate_similarity:
            duplicate_similarity = similarity
            possible_duplicate_of = existing.id
    duplicate_status = "possible_duplicate" if duplicate_similarity >= 0.82 else "unique"
    item = repo.add(
        kind="source_item",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="review_required" if duplicate_status == "possible_duplicate" else "accepted",
        data={
            **normalized_body,
            "content_hash": content_hash,
            "duplicate_status": duplicate_status,
            "duplicate_similarity": round(duplicate_similarity, 4),
            "possible_duplicate_of": possible_duplicate_of if duplicate_status == "possible_duplicate" else None,
            "rights_status": "confirmed",
        },
    )
    if body.get("callback_url"):
        webhook = repo.add(
            kind="webhook",
            organization_id=principal.organization_id,
            project_id=project_id,
            status="active",
            data={
                "url": str(body["callback_url"]),
                "events": ["generation.*", "research.*", "publication.*"],
                "source_item_id": item.id,
                "callback": True,
                "last_success_at": None,
                "delivery_count": 0,
            },
        )
        repo.update(item, data={"callback_webhook_id": webhook.id})
    if idempotency_key:
        save_idempotent_response(
            session,
            actor_id=principal.actor_id,
            endpoint=endpoint,
            key=idempotency_key,
            payload=body,
            status_code=202,
            response={"source_item_id": item.id, "status": item.status},
        )
    return item, False


@router.post("/projects/{project_id}/source-items", status_code=202, tags=["sources"])
async def create_source_item(
    project_id: str,
    payload: SourceItemCreate,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("sources:write")
    body = payload.model_dump(mode="json")
    if payload.source_type == "url" and not payload.content_markdown.strip():
        if not payload.canonical_url:
            raise HTTPException(422, "canonical_url is required when URL content is not supplied")
        try:
            article = extract_article(await fetch_public_text(str(payload.canonical_url)))
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(422, f"URL extraction failed: {exc}") from exc
        body.update({key: value for key, value in article.items() if value is not None})
        body["title"] = payload.title or article["title"]
        body["metadata"] = {**payload.metadata, **article["metadata"]}
    item, duplicate = _create_source_item(
        project_id=project_id,
        body=body,
        principal=principal,
        session=session,
        idempotency_key=idempotency_key,
        endpoint=f"POST:/v1/projects/{project_id}/source-items",
    )
    response = {
        "source_item_id": item.id,
        "status": item.status,
        "duplicate": duplicate,
        "links": {"self": f"/v1/source-items/{item.id}"},
    }
    if not duplicate:
        await EventSink(settings).emit(
            session,
            organization_id=principal.organization_id,
            project_id=project_id,
            event_type="source.accepted",
            resource_type="source_item",
            resource_id=item.id,
            correlation_id=item.id,
        )
    research_requested = payload.processing.get("research") in {True, "required"} or payload.processing.get("run_research") is True
    if research_requested and not duplicate:
        repo = ResourceRepository(session)
        run = repo.add(
            kind="research_run",
            organization_id=principal.organization_id,
            project_id=project_id,
            status="queued",
            data={
                "objective": f"Find fresh evidence and useful audience angles around {item.data.get('title')}",
                "source_item_id": item.id,
                "recency_days": int(payload.processing.get("recency_days", 30)),
                "max_candidates": int(payload.processing.get("max_candidates", 5)),
                "trigger_type": "source",
                "provider": "parallel",
            },
        )
        background.add_task(_run_research_task, run.id, get_settings())
        response["research_run_id"] = run.id
    return response


@router.post("/content-items", status_code=202, tags=["sources"])
async def create_content_item(
    payload: ContentItemCreate,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("sources:write")
    body = {
        "source_type": "api",
        "external_id": payload.external_id,
        "canonical_url": str(payload.url) if payload.url else None,
        "title": payload.title,
        "content_markdown": payload.content,
        "language": payload.language,
        "published_at": payload.published_at.isoformat() if payload.published_at else None,
        "author": payload.metadata.get("author"),
        "tags": payload.metadata.get("tags", []),
        "rights_confirmed": payload.rights_confirmed,
        "metadata": payload.metadata,
        "processing": payload.automation,
        "callback_url": str(payload.callback_url) if payload.callback_url else None,
    }
    if payload.type == "url" and not payload.content.strip():
        if not payload.url:
            raise HTTPException(422, "url is required for URL ingestion")
        try:
            article = extract_article(await fetch_public_text(str(payload.url)))
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(422, f"URL extraction failed: {exc}") from exc
        body.update({key: value for key, value in article.items() if value is not None})
        body["title"] = payload.title or article["title"]
        body["metadata"] = {**payload.metadata, **article["metadata"]}
    item, duplicate = _create_source_item(
        project_id=payload.project_id,
        body=body,
        principal=principal,
        session=session,
        idempotency_key=idempotency_key,
        endpoint="POST:/v1/content-items",
    )
    response: dict[str, Any] = {"source_item_id": item.id, "status": item.status, "duplicate": duplicate}
    if not duplicate:
        await EventSink(settings).emit(
            session,
            organization_id=principal.organization_id,
            project_id=payload.project_id,
            event_type="source.accepted",
            resource_type="source_item",
            resource_id=item.id,
            correlation_id=item.id,
        )
    if payload.automation.get("run_research") and not duplicate:
        run = ResourceRepository(session).add(
            kind="research_run",
            organization_id=principal.organization_id,
            project_id=payload.project_id,
            status="queued",
            data={
                "objective": f"Find fresh evidence and useful audience angles around {item.data.get('title')}",
                "source_item_id": item.id,
                "recency_days": int(payload.automation.get("recency_days", 30)),
                "max_candidates": int(payload.automation.get("create_ideas", 5)),
                "trigger_type": "source",
                "provider": "parallel",
            },
        )
        background.add_task(_run_research_task, run.id, get_settings())
        response["research_run_id"] = run.id
    if payload.automation.get("generate_best") and not duplicate:
        outputs = payload.automation.get("outputs") or []
        ratios = [item.get("aspect_ratio") for item in outputs if item.get("aspect_ratio") in {"9:16", "16:9"}]
        target_seconds = next(
            (int(item.get("target_seconds")) for item in outputs if item.get("target_seconds")),
            30,
        )
        generation = await create_generation(
            project_id=payload.project_id,
            payload=GenerationCreate(
                source_item_id=item.id,
                aspect_ratios=ratios or ["9:16"],
                target_duration_seconds=target_seconds,
                approval_mode="final_only",
            ),
            request=request,
            idempotency_key=f"source:{item.id}:generation:v1",
            principal=principal,
            session=session,
        )
        response["generation_job_id"] = generation["generation_job_id"]
        response["status_url"] = generation["status_url"]
        generated_job = ResourceRepository(session).get_any(generation["generation_job_id"], kind="generation_job")
        if generated_job:
            ResourceRepository(session).update(
                generated_job,
                data={"automatic": True, "trigger_type": "source_automation"},
            )
    return response


@router.get("/projects/{project_id}/source-items", tags=["sources"])
def list_source_items(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="source_item"
        )
    )


@router.get("/source-items/{source_item_id}", tags=["sources"])
def get_source_item(
    source_item_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:read")
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), source_item_id, principal, kind="source_item")
    )


@router.post("/sources/{source_id}/poll", status_code=202, tags=["sources"])
async def poll_source(
    source_id: str,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    source = require_resource(repo, source_id, principal, kind="source")
    if source.data.get("type") != "rss" or not source.data.get("url"):
        raise HTTPException(409, "Only configured RSS/Atom sources can be polled")
    config = dict(source.data.get("config") or {})
    if not config.get("rights_confirmed"):
        raise HTTPException(409, "RSS source rights must be confirmed before polling")
    try:
        fetched = await fetch_public_text(str(source.data["url"]))
    except (ValueError, httpx.HTTPError) as exc:
        repo.update(source, status="degraded", data={"last_error": str(exc), "last_checked": datetime.now(UTC).isoformat()})
        raise HTTPException(422, f"RSS fetch failed: {exc}") from exc
    parsed = feedparser.parse(fetched["text"])
    include_patterns = list(config.get("include_url_patterns") or ["*"])
    exclude_patterns = list(config.get("exclude_url_patterns") or [])
    allowed_languages = {str(value).lower() for value in config.get("languages") or []}
    required_tags = {str(value).lower() for value in config.get("tags") or []}
    minimum_length = int(config.get("minimum_content_length", 0))
    max_items = min(int(config.get("max_items_per_poll", 20)), 100)
    created: list[str] = []
    duplicates: list[str] = []
    research_runs: list[str] = []
    for entry in list(parsed.entries)[:max_items]:
        link = str(entry.get("link") or "")
        if not link:
            continue
        link = validate_public_url(link)
        if not any(fnmatch.fnmatch(link, pattern) for pattern in include_patterns):
            continue
        if any(fnmatch.fnmatch(link, pattern) for pattern in exclude_patterns):
            continue
        entry_tags = {str(tag.get("term") or "").lower() for tag in entry.get("tags", [])}
        if required_tags and not required_tags.intersection(entry_tags):
            continue
        language = str(entry.get("language") or config.get("language") or "en").lower()
        if allowed_languages and language not in allowed_languages:
            continue
        contents = entry.get("content") or []
        content = str(contents[0].get("value") if contents else entry.get("summary") or entry.get("description") or "")
        if len(content.strip()) < minimum_length:
            continue
        published_at = None
        if entry.get("published_parsed"):
            published_at = datetime(*entry.published_parsed[:6], tzinfo=UTC).isoformat()
        body = {
            "source_type": "rss",
            "source_id": source.id,
            "external_id": str(entry.get("id") or link),
            "canonical_url": link,
            "title": str(entry.get("title") or "RSS entry")[:300],
            "content_markdown": content[:500_000],
            "language": language,
            "published_at": published_at,
            "author": str(entry.get("author") or "") or None,
            "tags": sorted(entry_tags),
            "rights_confirmed": True,
            "metadata": {
                "feed_url": source.data["url"],
                "prompt_injection_score": prompt_injection_score(content),
                "retrieved_content_is_data": True,
            },
            "processing": config.get("processing", {}),
        }
        item, duplicate = _create_source_item(
            project_id=source.project_id or "",
            body=body,
            principal=principal,
            session=session,
            idempotency_key=f"rss:{source.id}:{body['external_id']}",
            endpoint=f"POST:/v1/sources/{source.id}/poll:item",
        )
        (duplicates if duplicate else created).append(item.id)
        if not duplicate and config.get("run_research", True):
            run = repo.add(
                kind="research_run",
                organization_id=principal.organization_id,
                project_id=source.project_id,
                status="queued",
                data={
                    "objective": f"Find fresh evidence and audience angles around {item.data.get('title')}",
                    "source_item_id": item.id,
                    "recency_days": int(config.get("recency_days", 30)),
                    "max_candidates": int(config.get("max_candidates", 5)),
                    "trigger_type": "rss",
                    "provider": "parallel",
                },
            )
            background.add_task(_run_research_task, run.id, settings)
            research_runs.append(run.id)
    repo.update(
        source,
        status="healthy",
        data={
            "last_checked": datetime.now(UTC).isoformat(),
            "next_poll_at": (
                datetime.now(UTC) + timedelta(minutes=int(config.get("poll_interval_minutes", 60)))
            ).isoformat(),
            "last_error": None,
            "last_poll": {"created": len(created), "duplicates": len(duplicates)},
        },
    )
    return {
        "source_id": source.id,
        "status": "accepted",
        "created_item_ids": created,
        "duplicate_item_ids": duplicates,
        "research_run_ids": research_runs,
    }


@router.post("/projects/{project_id}/research-profiles", status_code=201, tags=["research"])
def create_research_profile(
    project_id: str,
    payload: ResearchProfileCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:run")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    profile = repo.add(
        kind="research_profile",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="active",
        data={
            **payload.model_dump(mode="json"),
            "next_run_at": (
                payload.next_run_at or datetime.now(UTC) + timedelta(hours=payload.interval_hours)
            ).isoformat(),
            "last_run_at": None,
        },
    )
    return ResourceRepository.serialize(profile)


@router.get("/projects/{project_id}/research-profiles", tags=["research"])
def list_research_profiles(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id,
            project_id=project_id,
            kind="research_profile",
        )
    )


def enqueue_due_research_profiles(
    session: Session,
    background: BackgroundTasks,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> list[str]:
    current = now or datetime.now(UTC)
    repo = ResourceRepository(session)
    queued: list[str] = []
    profiles = list(
        session.scalars(
            select(Resource).where(Resource.kind == "research_profile", Resource.status == "active")
        )
    )
    for profile in profiles:
        next_run_value = profile.data.get("next_run_at")
        if not next_run_value:
            continue
        try:
            next_run = datetime.fromisoformat(str(next_run_value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)
        if next_run > current:
            continue
        project = repo.get_any(profile.project_id or "", kind="project")
        if not project or project.status != "active" or project.data.get("autopilot_paused"):
            continue
        run = repo.add(
            kind="research_run",
            organization_id=profile.organization_id,
            project_id=profile.project_id,
            status="queued",
            data={
                "objective": profile.data["objective"],
                "recency_days": int(profile.data.get("recency_days", 30)),
                "max_candidates": int(profile.data.get("max_candidates", 5)),
                "trigger_type": "scheduled",
                "research_profile_id": profile.id,
                "timezone": profile.data.get("timezone", project.data.get("timezone", "UTC")),
                "provider": "parallel",
            },
        )
        interval_hours = int(profile.data.get("interval_hours", 24))
        repo.update(
            profile,
            data={
                "last_run_at": current.isoformat(),
                "next_run_at": (current + timedelta(hours=interval_hours)).isoformat(),
                "last_run_id": run.id,
            },
        )
        background.add_task(_run_research_task, run.id, settings)
        queued.append(run.id)
    return queued


@router.post("/internal/research/run-due", include_in_schema=False)
def run_due_research(
    background: BackgroundTasks,
    _: dict[str, Any] = Depends(require_google_service_identity),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    queued = enqueue_due_research_profiles(session, background, settings)
    return {"due": len(queued), "queued": queued}


async def poll_due_rss_sources(
    session: Session,
    background: BackgroundTasks,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now(UTC)
    sources = list(
        session.scalars(
            select(Resource).where(
                Resource.kind == "source",
                Resource.status.in_(("healthy", "degraded")),
                Resource.data["type"].as_string() == "rss",
            )
        )
    )
    results: list[dict[str, Any]] = []
    for source in sources:
        next_poll_value = source.data.get("next_poll_at")
        if next_poll_value:
            try:
                next_poll = datetime.fromisoformat(str(next_poll_value).replace("Z", "+00:00"))
                if next_poll.tzinfo is None:
                    next_poll = next_poll.replace(tzinfo=UTC)
                if next_poll > current:
                    continue
            except ValueError:
                pass
        project = ResourceRepository(session).get_any(source.project_id or "", kind="project")
        if not project or project.status != "active" or project.data.get("autopilot_paused"):
            continue
        system_principal = Principal(
            actor_id="scheduler",
            organization_id=source.organization_id,
            project_id=source.project_id,
            role="service_account",
            scopes=ALL_SCOPES,
        )
        try:
            result = await poll_source(
                source.id,
                background,
                principal=system_principal,
                session=session,
                settings=settings,
            )
            results.append({"source_id": source.id, "status": "accepted", **result})
        except HTTPException as exc:
            results.append({"source_id": source.id, "status": "failed", "error": str(exc.detail)})
    return results


@router.post("/internal/automation/run-due", include_in_schema=False)
async def run_due_automation(
    background: BackgroundTasks,
    _: dict[str, Any] = Depends(require_google_service_identity),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    sources = await poll_due_rss_sources(session, background, settings)
    research = enqueue_due_research_profiles(session, background, settings)
    backlog = enqueue_backlog_replenishment(session, background, settings)
    publications = await refresh_processing_publications(session, settings)
    webhooks = await retry_due_webhook_deliveries(session, settings)
    alerts = evaluate_operational_alerts(session)
    return {
        "rss": sources,
        "research_run_ids": research,
        "backlog_research_run_ids": backlog,
        "publications": publications,
        "webhook_deliveries": webhooks,
        "alerts": alerts,
    }


def enqueue_backlog_replenishment(
    session: Session,
    background: BackgroundTasks,
    settings: Settings,
) -> list[str]:
    repo = ResourceRepository(session)
    queued: list[str] = []
    projects = list(
        session.scalars(select(Resource).where(Resource.kind == "project", Resource.status == "active"))
    )
    for project in projects:
        if project.data.get("autopilot_paused"):
            continue
        target = int(((project.data.get("settings") or {}).get("research") or {}).get("backlog_target", 0))
        if target <= 0:
            continue
        ideas = repo.list(
            organization_id=project.organization_id,
            project_id=project.id,
            kind="idea",
            limit=200,
        )
        videos = repo.list(
            organization_id=project.organization_id,
            project_id=project.id,
            kind="video",
            limit=200,
        )
        ready_count = sum(item.status in {"ready", "draft", "planned"} for item in ideas) + sum(
            item.status in {"approval_required", "approved"} for item in videos
        )
        if ready_count >= target:
            continue
        existing = session.scalar(
            select(Resource.id).where(
                Resource.kind == "research_run",
                Resource.project_id == project.id,
                Resource.status.in_(("queued", "running")),
                Resource.data["trigger_type"].as_string() == "backlog",
            )
        )
        if existing:
            continue
        gap = min(3, target - ready_count)
        run = repo.add(
            kind="research_run",
            organization_id=project.organization_id,
            project_id=project.id,
            status="queued",
            data={
                "objective": f"Find {gap} fresh evidence-backed content opportunities for {project.data.get('name')}",
                "recency_days": int(
                    ((project.data.get("settings") or {}).get("research") or {}).get("recency_days", 30)
                ),
                "max_candidates": gap,
                "trigger_type": "backlog",
                "backlog_target": target,
                "backlog_before": ready_count,
                "provider": "parallel",
            },
        )
        background.add_task(_run_research_task, run.id, settings)
        queued.append(run.id)
    return queued


def evaluate_operational_alerts(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    repo = ResourceRepository(session)
    firing: list[dict[str, Any]] = []

    def add_alert(resource: Resource, alert_type: str, message: str, severity: str = "warning") -> None:
        key = f"{alert_type}:{resource.id}"
        firing.append(
            {
                "dedupe_key": key,
                "alert_type": alert_type,
                "organization_id": resource.organization_id,
                "project_id": resource.project_id,
                "resource_id": resource.id,
                "message": message,
                "severity": severity,
            }
        )

    resources = list(session.scalars(select(Resource)))
    for resource in resources:
        updated_at = resource.updated_at if resource.updated_at.tzinfo else resource.updated_at.replace(tzinfo=UTC)
        if (
            resource.kind == "generation_job"
            and resource.status in {"queued", "running"}
            and updated_at < current - timedelta(minutes=30)
        ):
            add_alert(resource, "stuck_job", "Generation job has made no progress for more than 30 minutes", "critical")
        if resource.kind == "project":
            budget = dict((resource.data.get("settings") or {}).get("budget") or {})
            limit = float(budget.get("monthly_usd", 0))
            used = float(budget.get("used_usd", 0))
            if limit and used >= limit:
                add_alert(resource, "budget_breach", f"Project budget is exhausted ({used:.2f}/{limit:.2f} USD)", "critical")
        if resource.kind == "metric_checkpoint" and resource.status in {"scheduled", "collecting"}:
            due_value = resource.data.get("scheduled_at")
            try:
                due = datetime.fromisoformat(str(due_value).replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=UTC)
                if due < current - timedelta(hours=2):
                    add_alert(resource, "stale_metrics", "Metric checkpoint is more than two hours overdue")
            except (TypeError, ValueError):
                pass
        if resource.kind == "connection" and resource.status in {"reauth", "error"}:
            add_alert(resource, "oauth_failure", "Provider connection requires reauthorization", "critical")

    recent_failures = [
        resource
        for resource in resources
        if resource.kind == "audit_event"
        and (resource.created_at if resource.created_at.tzinfo else resource.created_at.replace(tzinfo=UTC))
        >= current - timedelta(minutes=15)
        and ("failed" in str(resource.data.get("event_type")) or "blocked" in str(resource.data.get("event_type")))
    ]
    failures_by_org: dict[str, list[Resource]] = {}
    for failure in recent_failures:
        failures_by_org.setdefault(failure.organization_id, []).append(failure)
    for _organization_id, failures in failures_by_org.items():
        if len(failures) >= 5:
            latest = failures[0]
            add_alert(latest, "error_spike", f"{len(failures)} failures or blocks occurred in 15 minutes", "critical")

    active_keys: set[str] = set()
    created_or_updated: list[str] = []
    for definition in firing:
        active_keys.add(definition["dedupe_key"])
        existing = session.scalar(
            select(Resource).where(
                Resource.kind == "alert",
                Resource.data["dedupe_key"].as_string() == definition["dedupe_key"],
            )
        )
        data = {
            **definition,
            "last_evaluated_at": current.isoformat(),
            "first_fired_at": existing.data.get("first_fired_at") if existing else current.isoformat(),
        }
        if existing:
            repo.update(existing, status="firing", data=data)
            created_or_updated.append(existing.id)
        else:
            alert = repo.add(
                kind="alert",
                organization_id=definition["organization_id"],
                project_id=definition["project_id"],
                status="firing",
                data=data,
            )
            created_or_updated.append(alert.id)
    for alert in [resource for resource in resources if resource.kind == "alert" and resource.status == "firing"]:
        if alert.data.get("dedupe_key") not in active_keys:
            repo.update(alert, status="resolved", data={"resolved_at": current.isoformat()})
    return {"firing": len(firing), "alert_ids": created_or_updated}


async def refresh_processing_publications(session: Session, settings: Settings) -> list[dict[str, Any]]:
    if settings.provider_mode != "live":
        return []
    repo = ResourceRepository(session)
    publications = list(
        session.scalars(
            select(Resource).where(
                Resource.kind == "publication",
                Resource.status.in_(("processing", "uploading", "retryable_failure")),
                Resource.data["platform"].as_string() == "youtube",
            )
        )
    )
    results: list[dict[str, Any]] = []
    for publication in publications:
        if not publication.data.get("external_post_id"):
            continue
        await _refresh_youtube_publication(repo, publication, settings)
        results.append({"publication_id": publication.id, "status": publication.status})
    return results


async def retry_due_webhook_deliveries(session: Session, settings: Settings) -> list[dict[str, Any]]:
    current = datetime.now(UTC)
    repo = ResourceRepository(session)
    due = list(
        session.scalars(
            select(Resource).where(
                Resource.kind == "webhook_delivery",
                Resource.status == "retry_scheduled",
            )
        )
    )
    results: list[dict[str, Any]] = []
    for delivery in due:
        next_attempt = delivery.data.get("next_attempt_at")
        if next_attempt:
            try:
                parsed = datetime.fromisoformat(str(next_attempt).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                if parsed > current:
                    continue
            except ValueError:
                pass
        webhook = repo.get_any(str(delivery.data.get("webhook_id") or ""), kind="webhook")
        if not webhook or webhook.status != "active" or not delivery.data.get("event"):
            continue
        await _deliver_webhook_attempt(
            repo,
            webhook,
            dict(delivery.data["event"]),
            settings,
            delivery=delivery,
        )
        results.append({"delivery_id": delivery.id, "status": delivery.status, "attempt": delivery.data["attempt"]})
    return results


async def _run_research_task(run_id: str, settings: Settings) -> None:
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        run = repo.get_any(run_id, kind="research_run")
        if not run:
            return
        repo.update(run, status="running", data={"started_at": datetime.now(UTC).isoformat()})
        try:
            packet = await ParallelSearchProvider(settings).search(
                run.data["objective"], recency_days=int(run.data.get("recency_days", 30))
            )
            repo.update(
                run,
                status="completed",
                data={
                    "parallel_request_ids": [packet.request_id],
                    "parallel_result_metadata": packet.raw,
                    "sources": packet.sources,
                    "claims": packet.claims,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
            score = min(92, 61 + len(packet.sources) * 7)
            for index in range(min(int(run.data.get("max_candidates", 5)), 3)):
                title = (
                    "One lesson, three reusable learning assets",
                    "The feedback loop most course creators skip",
                    "A 30-second fix for an unclear course outcome",
                )[index]
                angle = (
                    "Show the three-part transformation with one concrete example",
                    "Contrast late generic feedback with immediate actionable practice",
                    "Rewrite a vague topic as a measurable learner outcome",
                )[index]
                fingerprint = hashlib.sha256(f"{title}|{angle}".lower().encode()).hexdigest()
                muted = False
                for mute in repo.list(
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    kind="topic_mute",
                    statuses=("active",),
                    limit=200,
                ):
                    expires = mute.data.get("muted_until")
                    active = bool(mute.data.get("permanent")) or (
                        bool(expires) and datetime.fromisoformat(str(expires)) > datetime.now(UTC)
                    )
                    if active and mute.data.get("topic_fingerprint") == fingerprint:
                        muted = True
                        break
                if muted:
                    continue
                candidate = repo.add(
                    kind="topic_candidate",
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    status="candidate",
                    data={
                        "research_run_id": run.id,
                        "title": title,
                        "angle": angle,
                        "audience": "Independent teachers",
                        "why_now": "Relevant to active creator workflows and current short-form discovery.",
                        "source_ids": [source["id"] for source in packet.sources],
                        "supported_claims": [claim for claim in packet.claims if claim.get("status") == "supported"],
                        "unresolved_questions": [
                            claim.get("claim") or claim.get("text")
                            for claim in packet.claims
                            if claim.get("status") not in {"supported", "confirmed"}
                        ],
                        "topic_opportunity_score": score - index * 5,
                        "score_confidence": min(0.86, 0.48 + len(packet.sources) * 0.08),
                        "risk_flags": [],
                        "freshness_expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    },
                )
                if run.data.get("trigger_type") == "backlog":
                    repo.add(
                        kind="idea",
                        organization_id=run.organization_id,
                        project_id=run.project_id,
                        status="draft",
                        data={
                            "title": title,
                            "hook": angle,
                            "audience": "Independent teachers",
                            "objective": "education",
                            "format": "educational_explainer",
                            "topic_candidate_id": candidate.id,
                            "research_run_id": run.id,
                            "source_ids": candidate.data["source_ids"],
                            "topic_opportunity_score": candidate.data["topic_opportunity_score"],
                            "score_confidence": candidate.data["score_confidence"],
                            "provenance": "scheduled_backlog_replenishment",
                        },
                    )
            await EventSink(settings).emit(
                session,
                organization_id=run.organization_id,
                project_id=run.project_id,
                event_type="research.completed",
                resource_type="research_run",
                resource_id=run.id,
                payload={"candidate_count": min(int(run.data.get("max_candidates", 5)), 3)},
                correlation_id=run.id,
            )
        except Exception as exc:
            repo.update(run, status="failed", data={"error": str(exc), "retryable": True})
            await EventSink(settings).emit(
                session,
                organization_id=run.organization_id,
                project_id=run.project_id,
                event_type="research.failed",
                resource_type="research_run",
                resource_id=run.id,
                payload={"error": str(exc)},
                correlation_id=run.id,
            )


@router.post("/projects/{project_id}/research-runs", status_code=202, tags=["research"])
def create_research_run(
    project_id: str,
    payload: ResearchRunCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("research:run")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    if payload.source_item_id:
        require_resource(repo, payload.source_item_id, principal, kind="source_item", project_id=project_id)
    run = repo.add(
        kind="research_run",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="queued",
        data={**payload.model_dump(), "trigger_type": "manual", "provider": "parallel"},
    )
    background.add_task(_run_research_task, run.id, settings)
    return {"research_run_id": run.id, "status": "queued", "status_url": f"/v1/research-runs/{run.id}"}


@router.get("/projects/{project_id}/research-runs", tags=["research"])
def list_research_runs(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="research_run"
        )
    )


@router.get("/research-runs/{run_id}", tags=["research"])
def get_research_run(
    run_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:read")
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), run_id, principal, kind="research_run")
    )


@router.get("/projects/{project_id}/topic-candidates", tags=["research"])
def list_topic_candidates(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="topic_candidate"
        )
    )


@router.post("/topic-candidates/{candidate_id}/select", tags=["research"])
def select_candidate(
    candidate_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:run")
    repo = ResourceRepository(session)
    candidate = require_resource(repo, candidate_id, principal, kind="topic_candidate")
    existing_idea = session.scalar(
        select(Resource).where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == candidate.project_id,
            Resource.kind == "idea",
            Resource.data["topic_candidate_id"].as_string() == candidate.id,
        )
    )
    idea = existing_idea or repo.add(
        kind="idea",
        organization_id=principal.organization_id,
        project_id=candidate.project_id,
        status="draft",
        data={
            "title": candidate.data.get("title"),
            "hook": candidate.data.get("angle"),
            "audience": candidate.data.get("audience"),
            "objective": "education",
            "format": (candidate.data.get("suggested_formats") or ["educational_explainer"])[0],
            "topic_candidate_id": candidate.id,
            "research_run_id": candidate.data.get("research_run_id"),
            "source_ids": candidate.data.get("source_ids", []),
            "topic_opportunity_score": candidate.data.get("topic_opportunity_score"),
            "score_confidence": candidate.data.get("score_confidence"),
            "created_by_type": "candidate_conversion",
            "created_by_id": principal.actor_id,
        },
    )
    updated = repo.update(candidate, status="selected", data={"idea_id": idea.id})
    return {**ResourceRepository.serialize(updated), "idea_id": idea.id}


@router.post("/topic-candidates/{candidate_id}/reject", tags=["research"])
def reject_candidate(
    candidate_id: str,
    payload: ReviewAction,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:run")
    repo = ResourceRepository(session)
    candidate = require_resource(repo, candidate_id, principal, kind="topic_candidate")
    return ResourceRepository.serialize(
        repo.update(candidate, status="rejected", data={"review": payload.model_dump(exclude_none=True)})
    )


@router.post("/topic-candidates/{candidate_id}/mute", tags=["research"])
def mute_candidate(
    candidate_id: str,
    payload: TopicMute,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("research:run")
    repo = ResourceRepository(session)
    candidate = require_resource(repo, candidate_id, principal, kind="topic_candidate")
    if not payload.permanent and payload.muted_until is None:
        raise HTTPException(422, "muted_until is required unless permanent=true")
    mute = repo.add(
        kind="topic_mute",
        organization_id=principal.organization_id,
        project_id=candidate.project_id,
        status="active",
        data={
            "topic_candidate_id": candidate.id,
            "topic_fingerprint": hashlib.sha256(
                f"{candidate.data.get('title', '')}|{candidate.data.get('angle', '')}".lower().encode()
            ).hexdigest(),
            "reason": payload.reason,
            "muted_until": payload.muted_until.isoformat() if payload.muted_until else None,
            "permanent": payload.permanent,
            "created_by": principal.actor_id,
        },
    )
    repo.update(candidate, status="muted", data={"mute_id": mute.id})
    return ResourceRepository.serialize(mute)


@router.post("/projects/{project_id}/ideas", status_code=201, tags=["ideas"])
def create_idea(
    project_id: str,
    payload: IdeaCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    if payload.topic_candidate_id:
        require_resource(repo, payload.topic_candidate_id, principal, kind="topic_candidate", project_id=project_id)
    idea = repo.add(
        kind="idea",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="draft",
        data={**payload.model_dump(), "created_by_type": "user", "created_by_id": principal.actor_id},
    )
    return ResourceRepository.serialize(idea)


@router.get("/projects/{project_id}/ideas", tags=["ideas"])
def list_ideas(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="idea"
        )
    )


@router.patch("/ideas/{idea_id}", tags=["ideas"])
def patch_idea(
    idea_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    idea = require_resource(repo, idea_id, principal, kind="idea")
    allowed = {key: value for key, value in payload.items() if key in {"title", "hook", "audience", "objective", "format", "status"}}
    new_status = allowed.pop("status", None)
    return ResourceRepository.serialize(repo.update(idea, data=allowed, status=new_status))


def _cadence_warnings(
    repo: ResourceRepository,
    *,
    project: Resource,
    platform: str,
    planned_at: str | None,
    exclude_id: str | None = None,
) -> list[str]:
    if not planned_at:
        return []
    try:
        target = datetime.fromisoformat(planned_at.replace("Z", "+00:00"))
    except ValueError:
        return ["planned_publish_at is not a valid ISO-8601 timestamp"]
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    publishing = dict((project.data.get("settings") or {}).get("publishing") or {})
    publishing = {
        **publishing,
        **dict((publishing.get("platforms") or {}).get(platform) or {}),
    }
    warnings: list[str] = []
    for period in publishing.get("blackout_periods") or []:
        try:
            start = datetime.fromisoformat(str(period["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(period["end"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if start <= target <= end:
            warnings.append("Publication falls inside a configured quiet/blackout period")
    minimum_gap = float(publishing.get("minimum_gap_hours", 0))
    daily_cap = int(publishing.get("daily_cap", publishing.get("max_posts_per_day", 0)))
    weekly_cap = int(publishing.get("weekly_cap", 0))
    allowed_windows = list(publishing.get("allowed_time_windows") or [])
    if allowed_windows:
        target_minutes = target.hour * 60 + target.minute
        in_window = False
        for window in allowed_windows:
            weekdays = window.get("weekdays") or list(range(7))
            if target.weekday() not in weekdays:
                continue
            try:
                start_hour, start_minute = map(int, str(window.get("start", "00:00")).split(":"))
                end_hour, end_minute = map(int, str(window.get("end", "23:59")).split(":"))
            except (TypeError, ValueError):
                continue
            if start_hour * 60 + start_minute <= target_minutes <= end_hour * 60 + end_minute:
                in_window = True
                break
        if not in_window:
            warnings.append("Publication is outside the configured platform time windows")
    scheduled_times: list[datetime] = []
    for kind in ("calendar_item", "publication"):
        for item in repo.list(
            organization_id=project.organization_id,
            project_id=project.id,
            kind=kind,
            limit=200,
        ):
            if item.id == exclude_id or item.data.get("platform") != platform:
                continue
            value = item.data.get("planned_publish_at") or item.data.get("scheduled_at")
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                scheduled_times.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
            except ValueError:
                continue
    if minimum_gap and any(abs((target - existing).total_seconds()) < minimum_gap * 3600 for existing in scheduled_times):
        warnings.append(f"Publication is closer than the {minimum_gap:g}-hour minimum platform gap")
    if daily_cap:
        day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        if sum(day_start <= existing < day_start + timedelta(days=1) for existing in scheduled_times) >= daily_cap:
            warnings.append(f"Publication exceeds the configured daily cap of {daily_cap}")
    if weekly_cap:
        week_start = target - timedelta(days=target.weekday(), hours=target.hour, minutes=target.minute, seconds=target.second)
        if sum(week_start <= existing < week_start + timedelta(days=7) for existing in scheduled_times) >= weekly_cap:
            warnings.append(f"Publication exceeds the configured weekly cap of {weekly_cap}")
    return warnings


@router.post("/ideas/{idea_id}/plan", status_code=201, tags=["ideas"])
def plan_idea(
    idea_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    idea = require_resource(repo, idea_id, principal, kind="idea")
    project = require_project(repo, idea.project_id or "", principal)
    cadence_warnings = _cadence_warnings(
        repo,
        project=project,
        platform=payload.get("platform", "youtube"),
        planned_at=payload.get("planned_publish_at"),
    )
    item = repo.add(
        kind="calendar_item",
        organization_id=principal.organization_id,
        project_id=idea.project_id,
        status="planned",
        data={
            "idea_id": idea.id,
            "title": idea.data.get("title"),
            "platform": payload.get("platform", "youtube"),
            "planned_generation_at": payload.get("planned_generation_at"),
            "planned_publish_at": payload.get("planned_publish_at"),
            "timezone": payload.get("timezone", "UTC"),
            "cadence_warnings": cadence_warnings,
        },
    )
    repo.update(idea, status="planned")
    return ResourceRepository.serialize(item)


@router.patch("/calendar-items/{item_id}", tags=["ideas"])
def patch_calendar_item(
    item_id: str,
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    item = require_resource(repo, item_id, principal, kind="calendar_item")
    project = require_project(repo, item.project_id or "", principal)
    allowed = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "platform",
            "planned_generation_at",
            "planned_publish_at",
            "timezone",
            "status",
            "responsible_user",
            "approval_deadline",
            "publication_window",
            "experiment_arm",
        }
    }
    status_value = allowed.pop("status", None)
    planned_at = allowed.get("planned_publish_at", item.data.get("planned_publish_at"))
    platform = allowed.get("platform", item.data.get("platform", "youtube"))
    allowed["cadence_warnings"] = _cadence_warnings(
        repo,
        project=project,
        platform=platform,
        planned_at=planned_at,
        exclude_id=item.id,
    )
    return ResourceRepository.serialize(repo.update(item, data=allowed, status=status_value))


@router.get("/projects/{project_id}/calendar", tags=["ideas"])
def get_calendar(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(ResourceRepository(session), project_id, principal)
    kinds = ("calendar_item", "research_run", "generation_job", "publication", "metric_checkpoint")
    items: list[dict[str, Any]] = []
    repo = ResourceRepository(session)
    for kind in kinds:
        items.extend(
            ResourceRepository.serialize(item)
            for item in repo.list(
                organization_id=principal.organization_id, project_id=project_id, kind=kind, limit=50
            )
        )
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"items": items, "timezone": require_project(repo, project_id, principal).data.get("timezone", "UTC")}


@router.post("/projects/{project_id}/generation-jobs", status_code=202, tags=["generations"])
async def create_generation(
    project_id: str,
    payload: GenerationCreate,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    body = payload.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = get_idempotent_response(
                session,
                actor_id=principal.actor_id,
                endpoint=f"POST:/v1/projects/{project_id}/generation-jobs",
                key=idempotency_key,
                payload=body,
            )
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        if cached:
            return cached[1]
    if project.status not in {"active", "review_required"}:
        raise HTTPException(409, f"Project is not ready for generation: {project.status}")
    if payload.idea_id:
        require_resource(repo, payload.idea_id, principal, kind="idea", project_id=project_id)
    if payload.source_item_id:
        require_resource(repo, payload.source_item_id, principal, kind="source_item", project_id=project_id)
    estimated = {
        "currency": "USD",
        "min": round(0.8 * len(payload.aspect_ratios) + 0.05 * payload.variants, 2),
        "max": round(4.2 * len(payload.aspect_ratios) + 0.25 * payload.variants, 2),
    }
    if estimated["max"] > payload.max_cost_usd:
        blocked = repo.add(
            kind="generation_job",
            organization_id=principal.organization_id,
            project_id=project_id,
            status="budget_blocked",
            data={
                **body,
                "stages": initial_stage_state(),
                "current_stage": "cost_guard",
                "progress": 0,
                "estimated_cost": estimated,
                "actual_cost_usd": 0,
                "max_cost_usd": payload.max_cost_usd,
                "hard_gates": {"budget": False},
                "idempotency_key": idempotency_key,
            },
        )
        response = {
            "generation_job_id": blocked.id,
            "status": "budget_blocked",
            "status_url": f"/v1/generation-jobs/{blocked.id}",
            "estimated_cost": estimated,
        }
        if idempotency_key:
            save_idempotent_response(
                session,
                actor_id=principal.actor_id,
                endpoint=f"POST:/v1/projects/{project_id}/generation-jobs",
                key=idempotency_key,
                payload=body,
                status_code=202,
                response=response,
            )
        return response
    job = repo.add(
        kind="generation_job",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="queued",
        data={
            **body,
            "stages": initial_stage_state(),
            "current_stage": "queued",
            "progress": 0,
            "estimated_cost": estimated,
            "actual_cost_usd": 0,
            "brand_profile_version": project.data.get("brand_profile_version", 1),
            "strategy_version": 1,
            "correlation_id": payload.source_item_id or payload.idea_id,
            "idempotency_key": idempotency_key,
        },
    )
    response = {
        "generation_job_id": job.id,
        "status": "queued",
        "status_url": f"/v1/generation-jobs/{job.id}",
        "estimated_cost": estimated,
    }
    if idempotency_key:
        save_idempotent_response(
            session,
            actor_id=principal.actor_id,
            endpoint=f"POST:/v1/projects/{project_id}/generation-jobs",
            key=idempotency_key,
            payload=body,
            status_code=202,
            response=response,
        )
    request.app.state.workflow.schedule(job.id)
    return response


@router.get("/projects/{project_id}/generation-jobs", tags=["generations"])
def list_generations(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="generation_job"
        )
    )


@router.get("/generation-jobs/{job_id}", tags=["generations"])
def get_generation(
    job_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:read")
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), job_id, principal, kind="generation_job")
    )


@router.post("/generation-jobs/{job_id}/cancel", tags=["generations"])
def cancel_generation(
    job_id: str,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    job = require_resource(repo, job_id, principal, kind="generation_job")
    task = request.app.state.workflow.tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    return ResourceRepository.serialize(
        repo.update(job, status="cancelled", data={"cancel_requested_at": datetime.now(UTC).isoformat()})
    )


@router.post("/generation-jobs/{job_id}/retry", status_code=202, tags=["generations"])
async def retry_generation(
    job_id: str,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    job = require_resource(repo, job_id, principal, kind="generation_job")
    if job.status not in {"failed", "blocked", "cancelled"}:
        raise HTTPException(409, f"Job cannot be retried from {job.status}")
    repo.update(job, status="queued", data={"last_error": None, "retry_requested_at": datetime.now(UTC).isoformat()})
    request.app.state.workflow.schedule(job.id)
    return {"generation_job_id": job.id, "status": "queued"}


@router.get("/generation-jobs/{job_id}/events", tags=["generations"])
def generation_events(
    job_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    job = require_resource(ResourceRepository(session), job_id, principal, kind="generation_job")
    events = ResourceRepository(session).list(
        organization_id=principal.organization_id, project_id=job.project_id, kind="audit_event", limit=200
    )
    filtered = [event for event in events if event.data.get("correlation_id") == job_id]
    return serialize_many(filtered)


@router.get("/projects/{project_id}/videos", tags=["videos"])
def list_videos(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("videos:read")
    require_project(ResourceRepository(session), project_id, principal)
    repo = ResourceRepository(session)
    items = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="video")
    return {
        "items": [serialize_video(repo, item, organization_id=principal.organization_id) for item in items],
        "next_cursor": None,
    }


@router.get("/videos/{video_id}", tags=["videos"])
def get_video(
    video_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("videos:read")
    repo = ResourceRepository(session)
    video = require_resource(repo, video_id, principal, kind="video")
    payload = serialize_video(repo, video, organization_id=principal.organization_id)
    for key, kind in (("qa_report", "qa_report"), ("score_report", "score_report"), ("script", "script"), ("storyboard", "storyboard")):
        resource_id = video.data.get(f"{key}_id")
        resource = repo.get(resource_id, organization_id=principal.organization_id, kind=kind) if resource_id else None
        payload[key] = ResourceRepository.serialize(resource) if resource else None
    payload["scenes"] = [
        ResourceRepository.serialize(item)
        for scene_id in video.data.get("scene_ids", [])
        if (item := repo.get(scene_id, organization_id=principal.organization_id, kind="scene"))
    ]
    return payload


@router.get("/video-versions/{version_id}", tags=["videos"])
def get_video_version(
    version_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("videos:read")
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), version_id, principal, kind="video_version")
    )


@router.post("/score-reports/{score_report_id}/override", tags=["videos"])
async def override_score(
    score_report_id: str,
    payload: ScoreOverride,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("videos:approve")
    repo = ResourceRepository(session)
    report = require_resource(repo, score_report_id, principal, kind="score_report")
    original = report.data.get(payload.score)
    overrides = list(report.data.get("overrides") or [])
    entry = {
        "score": payload.score,
        "original_value": original,
        "value": payload.value,
        "reason": payload.reason,
        "actor_id": principal.actor_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    overrides.append(entry)
    effective = dict(report.data.get("effective_scores") or {})
    effective[payload.score] = payload.value
    override = repo.add(
        kind="score_override",
        organization_id=principal.organization_id,
        project_id=report.project_id,
        status="active",
        data={"score_report_id": report.id, **entry, "hard_gates_unchanged": True},
    )
    repo.update(report, data={"overrides": overrides, "effective_scores": effective})
    await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=report.project_id,
        event_type="score.overridden",
        resource_type="score_report",
        resource_id=report.id,
        payload={"override_id": override.id, **entry, "hard_gates_unchanged": True},
    )
    return {
        "score_report": ResourceRepository.serialize(report),
        "override": ResourceRepository.serialize(override),
    }


def _review_video_version(
    *, version_id: str, review_status: str, payload: ReviewAction, principal: Principal, session: Session
) -> dict[str, Any]:
    principal.require("videos:approve")
    repo = ResourceRepository(session)
    version = require_resource(repo, version_id, principal, kind="video_version")
    approval = repo.add(
        kind="approval",
        organization_id=principal.organization_id,
        project_id=version.project_id,
        status=review_status,
        data={
            "video_version_id": version.id,
            "reviewer_id": principal.actor_id,
            **payload.model_dump(exclude_none=True),
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
    )
    repo.update(version, status=review_status, data={"approval_id": approval.id})
    video = repo.get_any(version.data["video_id"], kind="video")
    if video:
        repo.update(video, status=review_status)
        if review_status == "approved":
            for scene_id in video.data.get("scene_ids", []):
                scene = repo.get_any(scene_id, kind="scene")
                if scene and scene.organization_id == principal.organization_id:
                    repo.update(scene, data={"locked": True, "locked_by_approval_id": approval.id})
    return ResourceRepository.serialize(approval)


@router.post("/video-versions/{version_id}/approve", tags=["videos"])
def approve_video_version(
    version_id: str,
    payload: ReviewAction,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _review_video_version(
        version_id=version_id, review_status="approved", payload=payload, principal=principal, session=session
    )


@router.post("/video-versions/{version_id}/reject", tags=["videos"])
def reject_video_version(
    version_id: str,
    payload: ReviewAction,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _review_video_version(
        version_id=version_id, review_status="rejected", payload=payload, principal=principal, session=session
    )


@router.post("/video-versions/{version_id}/request-changes", tags=["videos"])
def request_video_changes(
    version_id: str,
    payload: ReviewAction,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return _review_video_version(
        version_id=version_id, review_status="changes_requested", payload=payload, principal=principal, session=session
    )


@router.post("/scenes/{scene_id}/regenerate", status_code=202, tags=["videos"])
def regenerate_scene(
    scene_id: str,
    payload: SceneRegenerate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    scene = require_resource(repo, scene_id, principal, kind="scene")
    if scene.data.get("locked"):
        raise HTTPException(409, "Locked scenes cannot be regenerated until explicitly unlocked")
    attempt_no = int(scene.data.get("attempt", 0)) + 1
    prompt = payload.visual_prompt or scene.data.get("visual_prompt")
    attempt = repo.add(
        kind="scene_attempt",
        organization_id=principal.organization_id,
        project_id=scene.project_id,
        status="queued",
        data={
            "scene_id": scene.id,
            "attempt": attempt_no,
            "reason": payload.reason,
            "visual_prompt": prompt,
            "model_id": "configured-veo-or-motion-fallback",
            "selective": True,
        },
    )
    repo.update(scene, status="regenerating", data={"attempt": attempt_no, "latest_attempt_id": attempt.id, "visual_prompt": prompt})
    return {"scene_id": scene.id, "attempt_id": attempt.id, "status": "queued", "locked_other_scenes": True}


@router.patch("/scripts/{script_id}", status_code=202, tags=["videos"])
async def revise_script(
    script_id: str,
    payload: ScriptPatch,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("generations:write")
    repo = ResourceRepository(session)
    script = require_resource(repo, script_id, principal, kind="script")
    videos = repo.list(
        organization_id=principal.organization_id,
        project_id=script.project_id,
        kind="video",
        limit=200,
    )
    video = next(
        (
            item
            for item in videos
            if item.data.get("script_id") == script.id
            or any(version.get("script_id") == script.id for version in item.data.get("versions", []))
        ),
        None,
    )
    if not video:
        raise HTTPException(409, "No rendered video is associated with this script")
    current_script = dict(script.data.get("script") or {})
    edits = payload.model_dump(exclude_none=True)
    reason = str(edits.pop("reason"))
    latest_version = repo.get_any(str(video.data.get("latest_version_id") or ""), kind="video_version")
    aspect_ratios = sorted(
        {
            str(version.get("aspect_ratio"))
            for version in video.data.get("versions", [])
            if version.get("aspect_ratio") in {"9:16", "16:9"}
        }
    ) or ["9:16"]
    duration_seconds = round(float(latest_version.data.get("duration_ms", 30_000)) / 1000) if latest_version else 30
    created = await create_generation(
        project_id=str(script.project_id),
        payload=GenerationCreate(
            title=str(edits.get("title") or current_script.get("title") or video.data.get("title")),
            aspect_ratios=aspect_ratios,
            target_duration_seconds=max(8, min(60, duration_seconds)),
            approval_mode="final_only",
            variants=1,
            max_cost_usd=20,
        ),
        request=request,
        idempotency_key=idempotency_key or f"script-revision:{script.id}:{hashlib.sha256(json.dumps(edits, sort_keys=True).encode()).hexdigest()[:16]}",
        principal=principal,
        session=session,
    )
    job = repo.get_any(created["generation_job_id"], kind="generation_job")
    if job:
        repo.update(
            job,
            data={
                "script_override": {**current_script, **edits},
                "revision_of_video_id": video.id,
                "supersedes_script_id": script.id,
                "revision_reason": reason,
                "correlation_id": str(script.data.get("generation_job_id") or script.id),
            },
        )
    return {
        **created,
        "video_id": video.id,
        "supersedes_script_id": script.id,
        "immutability": "The approved version remains unchanged; the revision will append a new version.",
    }


@router.get("/projects/{project_id}/connections", tags=["connections"])
def list_connections(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("integrations:read")
    require_project(ResourceRepository(session), project_id, principal)
    items = ResourceRepository(session).list(
        organization_id=principal.organization_id, project_id=project_id, kind="connection"
    )
    serialized = [ResourceRepository.serialize(item) for item in items]
    existing = {item.get("provider") for item in serialized}
    for provider in ("youtube", "instagram", "tiktok", "export"):
        if provider not in existing:
            serialized.append(
                {
                    "id": f"unconfigured_{provider}",
                    "project_id": project_id,
                    "provider": provider,
                    "status": "not_connected" if provider != "export" else "ready",
                    "display_name": provider.title(),
                    "capabilities": PROVIDER_CAPABILITIES[provider],
                    "creator_info": {
                        "display_name": "Not connected",
                        "audit_status": "unaudited",
                        "privacy_level_options": [],
                        "action_required": "Use the export package and finish in the provider UI",
                    }
                    if provider == "tiktok"
                    else None,
                }
            )
    return {"items": serialized, "next_cursor": None}


@router.post("/projects/{project_id}/connections/{provider}/authorize", tags=["connections"])
def authorize_connection(
    project_id: str,
    provider: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("integrations:write")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    if provider not in PROVIDER_CAPABILITIES:
        raise HTTPException(404, "Unknown provider")
    if provider != "youtube":
        return {
            "provider": provider,
            "status": "limited",
            "capabilities": PROVIDER_CAPABILITIES[provider],
            "action": "export_fallback" if provider in {"instagram", "tiktok"} else "ready",
            "creator_info": {
                "display_name": "Not connected",
                "audit_status": "unaudited",
                "privacy_level_options": [],
                "action_required": "Download the package and complete the post in TikTok",
            }
            if provider == "tiktok"
            else None,
        }
    if settings.provider_mode == "mock" or not (settings.youtube_client_id and settings.youtube_client_secret):
        connection = repo.add(
            kind="connection",
            organization_id=principal.organization_id,
            project_id=project_id,
            status="limited",
            data={
                "provider": "youtube",
                "display_name": "Mock YouTube Channel",
                "external_account_id": "mock_channel",
                "scopes": ["youtube.upload"],
                "capabilities": PROVIDER_CAPABILITIES["youtube"],
                "mode": "mock",
            },
        )
        return {"connection_id": connection.id, "status": "limited", "mode": "mock"}
    state_value = secrets.token_urlsafe(32)
    state_record = repo.add(
        kind="oauth_state",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="pending",
        data={
            "provider": "youtube",
            "state": state_value,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        },
    )
    authorize_url, code_verifier = youtube_authorization_url(settings, state=state_value)
    repo.update(state_record, data={"code_verifier": code_verifier})
    return {
        "state_id": state_record.id,
        "authorize_url": authorize_url,
        "expires_at": state_record.data["expires_at"],
    }


@router.get("/connections/youtube/callback", tags=["connections"])
def youtube_callback(
    code: str = Query(...),
    state_value: str = Query(..., alias="state"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    state_record = session.scalar(
        select(Resource).where(
            Resource.kind == "oauth_state",
            Resource.status == "pending",
            Resource.data["state"].as_string() == state_value,
        )
    )
    if not state_record:
        raise HTTPException(400, "Invalid or expired OAuth state")
    if datetime.fromisoformat(state_record.data["expires_at"]) < datetime.now(UTC):
        raise HTTPException(400, "OAuth state expired")
    repo = ResourceRepository(session)
    token_data = exchange_youtube_code(
        settings,
        code=code,
        state=state_value,
        code_verifier=str(state_record.data.get("code_verifier") or ""),
    )
    channel: dict[str, Any] = {}
    channel_error: str | None = None
    try:
        channel = resolve_youtube_channel(settings, token_data)
    except Exception as exc:
        channel_error = str(exc)
    connection = repo.add(
        kind="connection",
        organization_id=state_record.organization_id,
        project_id=state_record.project_id,
        status="healthy" if channel else "limited",
        data={
            "provider": "youtube",
            "display_name": channel.get("title") or "Connected YouTube channel",
            "external_account_id": channel.get("id") or settings.youtube_channel_id or "unresolved",
            "channel_privacy_status": channel.get("privacy_status"),
            "channel_resolution_error": channel_error,
            "scopes": token_data["scopes"],
            "capabilities": PROVIDER_CAPABILITIES["youtube"],
            "expires_at": token_data["expiry"],
            "mode": "live",
        },
    )
    secret_ref = store_oauth_secret(settings, connection.id, token_data)
    repo.update(connection, data={"secret_ref": secret_ref})
    repo.update(state_record, status="consumed", data={"connection_id": connection.id})
    return {
        "connection_id": connection.id,
        "status": connection.status,
        "project_id": connection.project_id,
        "channel_id": connection.data["external_account_id"],
        "channel_title": connection.data["display_name"],
        "message": "YouTube connected. You can close this tab and return to Agentic Video Studio.",
    }


@router.get("/connections/{connection_id}/capabilities", tags=["connections"])
def connection_capabilities(
    connection_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("integrations:read")
    connection = require_resource(ResourceRepository(session), connection_id, principal, kind="connection")
    provider = connection.data.get("provider", "export")
    return {
        "connection_id": connection.id,
        "provider": provider,
        "status": connection.status,
        "capabilities": connection.data.get("capabilities") or PROVIDER_CAPABILITIES.get(provider, {}),
    }


@router.delete("/connections/{connection_id}", status_code=204, tags=["connections"])
def disconnect_connection(
    connection_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> Response:
    principal.require("integrations:write")
    repo = ResourceRepository(session)
    connection = require_resource(repo, connection_id, principal, kind="connection")
    repo.update(connection, status="revoked", data={"revoked_at": datetime.now(UTC).isoformat(), "secret_ref": None})
    return Response(status_code=204)


def _active_provider_pause(session: Session, provider: str) -> Resource | None:
    return session.scalar(
        select(Resource).where(
            Resource.kind == "provider_control",
            Resource.status == "paused",
            Resource.data["provider"].as_string() == provider,
        )
    )


def _publishing_is_paused(session: Session, project: Resource, provider: str) -> str | None:
    if _active_provider_pause(session, provider):
        return f"New {provider} publication attempts are paused by the platform kill switch"
    publishing = dict((project.data.get("settings") or {}).get("publishing") or {})
    if publishing.get("pause_all_publications"):
        return "All publication attempts are paused for this project"
    if project.status == "paused" or project.data.get("autopilot_paused"):
        return "The project is paused"
    return None


def _ensure_publication_checkpoints(repo: ResourceRepository, publication: Resource) -> None:
    existing = repo.list(
        organization_id=publication.organization_id,
        project_id=publication.project_id,
        kind="metric_checkpoint",
        limit=200,
    )
    windows = {
        str(item.data.get("window"))
        for item in existing
        if item.data.get("publication_id") == publication.id
    }
    now = datetime.now(UTC)
    for window, delta in (("24h", timedelta(hours=24)), ("7d", timedelta(days=7))):
        if window in windows:
            continue
        repo.add(
            kind="metric_checkpoint",
            organization_id=publication.organization_id,
            project_id=publication.project_id,
            status="scheduled",
            data={
                "publication_id": publication.id,
                "window": window,
                "scheduled_at": (now + delta).isoformat(),
            },
        )


def _create_publication_export(
    repo: ResourceRepository,
    publication: Resource,
    settings: Settings,
) -> Resource:
    existing_id = publication.data.get("export_asset_id")
    if existing_id:
        existing = repo.get_any(existing_id, kind="media_asset")
        if existing:
            return existing

    version = repo.get_any(publication.data["video_version_id"], kind="video_version")
    asset = repo.get_any(version.data["render_asset_id"], kind="media_asset") if version else None
    video = repo.get_any(version.data["video_id"], kind="video") if version else None
    caption_asset = (
        repo.get_any(video.data.get("caption_asset_id"), kind="media_asset")
        if video and video.data.get("caption_asset_id")
        else None
    )
    if not version or not asset:
        raise HTTPException(409, "Publication media is unavailable")

    storage = MediaStorage(settings)
    video_path = Path(asset.data.get("local_path") or asset.data["storage_uri"])
    storage.materialize(storage_uri=asset.data.get("storage_uri"), local_path=video_path)
    captions_path = None
    if caption_asset:
        captions_path = Path(caption_asset.data.get("local_path") or caption_asset.data["storage_uri"])
        storage.materialize(storage_uri=caption_asset.data.get("storage_uri"), local_path=captions_path)

    output_path = (
        settings.storage_root
        / str(publication.project_id)
        / publication.id
        / "exports"
        / f"{publication.id}.zip"
    )
    result = create_export_package(
        video_path=video_path,
        captions_path=captions_path,
        output_path=output_path,
        metadata={
            "publication_id": publication.id,
            "video_version_id": version.id,
            "platform": publication.data.get("platform"),
            "title": publication.data.get("title"),
            "caption": publication.data.get("caption", ""),
            "hashtags": publication.data.get("hashtags", []),
            "privacy": publication.data.get("privacy"),
            "scheduled_at": publication.data.get("scheduled_at"),
            "synthetic_media_disclosure": publication.data.get("synthetic_media_disclosure", True),
            "video_checksum": version.data.get("checksum"),
        },
    )
    persisted = storage.persist(output_path, content_type="application/zip")
    export_asset = repo.add(
        kind="media_asset",
        organization_id=publication.organization_id,
        project_id=publication.project_id,
        status="ready",
        data={
            "type": "publication_export",
            "publication_id": publication.id,
            **persisted,
            "mime_type": "application/zip",
            "checksum": result["checksum"],
            "size_bytes": result["size_bytes"],
            "manifest": result["manifest"],
        },
    )
    repo.update(
        publication,
        data={
            "export_asset_id": export_asset.id,
            "export_package_url": persisted["public_path"],
            "export_checksum": result["checksum"],
        },
    )
    return export_asset


async def _refresh_youtube_publication(
    repo: ResourceRepository,
    publication: Resource,
    settings: Settings,
) -> Resource:
    external_id = publication.data.get("external_post_id")
    if not external_id:
        return publication
    connection = repo.get_any(publication.data.get("connection_id"), kind="connection")
    if not connection:
        return repo.update(publication, status="reauth", data={"status_error": "Connection is unavailable"})
    try:
        result = await asyncio.to_thread(
            get_youtube_video_status,
            settings,
            video_id=external_id,
            secret_ref=connection.data.get("secret_ref"),
        )
    except Exception as exc:
        return repo.update(
            publication,
            status="processing",
            data={"status_check_error": str(exc), "status_checked_at": datetime.now(UTC).isoformat()},
        )
    normalized = str(result.pop("status"))
    updates = {**result, "status_checked_at": datetime.now(UTC).isoformat()}
    if normalized == "published" and not publication.data.get("published_at"):
        updates["published_at"] = datetime.now(UTC).isoformat()
    repo.update(publication, status=normalized, data=updates)
    if publication.status == "published":
        _ensure_publication_checkpoints(repo, publication)
    return publication


@router.post("/admin/providers/{provider}/pause", tags=["admin"])
async def pause_provider_publications(
    provider: str,
    payload: ReviewAction,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("admin")
    if provider not in PROVIDER_CAPABILITIES:
        raise HTTPException(404, "Provider not found")
    repo = ResourceRepository(session)
    control = _active_provider_pause(session, provider)
    if control:
        return ResourceRepository.serialize(control)
    control = repo.add(
        kind="provider_control",
        organization_id=principal.organization_id,
        project_id=None,
        status="paused",
        data={
            "provider": provider,
            "reason": payload.comment or payload.reason_code or "Emergency pause",
            "paused_by": principal.actor_id,
            "paused_at": datetime.now(UTC).isoformat(),
        },
    )
    await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=None,
        event_type="provider.publications_paused",
        resource_type="provider_control",
        resource_id=control.id,
        payload={"provider": provider, "reason": control.data["reason"]},
    )
    return ResourceRepository.serialize(control)


@router.post("/admin/providers/{provider}/resume", tags=["admin"])
async def resume_provider_publications(
    provider: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("admin")
    control = _active_provider_pause(session, provider)
    if not control:
        return {"provider": provider, "status": "active"}
    repo = ResourceRepository(session)
    repo.update(
        control,
        status="active",
        data={"resumed_by": principal.actor_id, "resumed_at": datetime.now(UTC).isoformat()},
    )
    await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=None,
        event_type="provider.publications_resumed",
        resource_type="provider_control",
        resource_id=control.id,
        payload={"provider": provider},
    )
    return ResourceRepository.serialize(control)


@router.post("/publications", status_code=202, tags=["publishing"])
def prepare_publication(
    payload: PublicationCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("publications:write")
    repo = ResourceRepository(session)
    version = require_resource(repo, payload.video_version_id, principal, kind="video_version")
    project = require_project(repo, str(version.project_id), principal)
    paused_reason = _publishing_is_paused(session, project, payload.platform)
    if paused_reason:
        raise HTTPException(423, paused_reason)
    if version.status != "approved" and not payload.dry_run:
        raise HTTPException(409, "Video version must be approved before publication")
    if payload.connection_id.startswith("unconfigured_"):
        connection = None
    else:
        connection = require_resource(repo, payload.connection_id, principal, kind="connection")
    if connection and connection.data.get("provider") != payload.platform:
        raise HTTPException(422, "Connection provider does not match the publication platform")
    if payload.platform == "youtube" and settings.provider_mode == "live":
        if not connection or connection.status != "active":
            raise HTTPException(409, "An active YouTube connection is required")
    body = payload.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = get_idempotent_response(
                session, actor_id=principal.actor_id, endpoint="POST:/v1/publications", key=idempotency_key, payload=body
            )
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        if cached:
            return cached[1]
    capabilities = PROVIDER_CAPABILITIES[payload.platform]
    if payload.platform == "tiktok" and payload.privacy is not None:
        raise HTTPException(422, "TikTok privacy may not be preselected; creator info options are required")
    if payload.platform == "tiktok" and (
        not payload.creator_info_acknowledged
        or payload.allow_comments is None
        or payload.allow_duet is None
        or payload.allow_stitch is None
    ):
        raise HTTPException(
            422,
            "TikTok composer requires creator acknowledgement and manual comment/duet/stitch settings",
        )
    token = confirmation_token()
    requires_consent = bool(capabilities.get("requires_per_post_consent"))
    warnings = []
    if payload.platform in {"instagram", "tiktok"}:
        warnings.append("Official production publishing access is not active; export/draft fallback will be used.")
    warnings.extend(
        _cadence_warnings(
            repo,
            project=project,
            platform=payload.platform,
            planned_at=payload.scheduled_at.isoformat() if payload.scheduled_at else None,
        )
    )
    generation = repo.get_any(str(version.data.get("generation_job_id") or ""), kind="generation_job")
    publication = repo.add(
        kind="publication",
        organization_id=principal.organization_id,
        project_id=version.project_id,
        status="dry_run" if payload.dry_run else ("awaiting_consent" if requires_consent else "prepared"),
        data={
            **body,
            "confirmation_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "consent_required": requires_consent,
            "warnings": warnings,
            "capabilities": capabilities,
            "connection_status": connection.status if connection else "not_connected",
            "generation_job_id": version.data.get("generation_job_id"),
            "correlation_id": (
                generation.data.get("correlation_id") if generation else None
            )
            or version.data.get("generation_job_id")
            or version.id,
            "idempotency_key": idempotency_key,
        },
    )
    response = {
        "publication_id": publication.id,
        "plan_id": publication.id,
        "status": publication.status,
        "summary": f"Prepare {payload.title} for {payload.platform}",
        "warnings": warnings,
        "requires_user_consent": requires_consent,
        "confirmation_token": token,
        "dry_run": payload.dry_run,
        "planned_actions": [
            "validate_provider_capabilities",
            "validate_policy_and_cadence",
            "upload_or_create_export_package",
            "poll_provider_processing_status",
            "schedule_24h_and_7d_metrics",
        ],
        "estimated_external_cost_usd": 0,
    }
    if idempotency_key:
        save_idempotent_response(
            session,
            actor_id=principal.actor_id,
            endpoint="POST:/v1/publications",
            key=idempotency_key,
            payload=body,
            status_code=202,
            response=response,
        )
    return response


@router.post("/publications/{publication_id}/confirm", tags=["publishing"])
async def confirm_publication(
    publication_id: str,
    payload: PublicationConfirm,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("publications:write")
    repo = ResourceRepository(session)
    publication = require_resource(repo, publication_id, principal, kind="publication")
    if publication.status == "dry_run":
        return ResourceRepository.serialize(publication)
    if publication.status in {
        "uploading",
        "processing",
        "published",
        "rejected",
        "export_ready",
        "cancelled",
        "permanent_failure",
        "reauth",
    }:
        return ResourceRepository.serialize(publication)
    expected = publication.data.get("confirmation_token_hash", "")
    actual = hashlib.sha256(payload.confirmation_token.encode()).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(403, "Invalid confirmation token")
    if publication.data.get("consent_required") and not payload.explicit_consent:
        raise HTTPException(409, "Explicit per-post consent is required by this provider")
    platform = publication.data["platform"]
    project = require_project(repo, str(publication.project_id), principal)
    paused_reason = _publishing_is_paused(session, project, platform)
    if paused_reason:
        raise HTTPException(423, paused_reason)
    consumed_at = datetime.now(UTC).isoformat()
    if platform == "tiktok":
        repo.update(
            publication,
            status="export_ready",
            data={
                "confirmation_consumed_at": consumed_at,
                "consent_received_at": consumed_at,
                "fallback": "creator_finishes_in_tiktok",
            },
        )
        _create_publication_export(repo, publication, settings)
    elif platform in {"instagram", "export"}:
        repo.update(
            publication,
            status="export_ready",
            data={"confirmation_consumed_at": consumed_at, "fallback": "download_package"},
        )
        _create_publication_export(repo, publication, settings)
    elif platform == "youtube" and settings.provider_mode == "live":
        version = repo.get_any(publication.data["video_version_id"], kind="video_version")
        asset = repo.get_any(version.data["render_asset_id"], kind="media_asset") if version else None
        connection = repo.get_any(publication.data["connection_id"], kind="connection")
        if not version or not asset or not connection:
            raise HTTPException(409, "Publication media or connection is unavailable")
        storage = MediaStorage(settings)
        local_path = Path(asset.data.get("local_path") or asset.data["storage_uri"])
        try:
            storage.materialize(storage_uri=asset.data.get("storage_uri"), local_path=local_path)
        except Exception as exc:
            repo.update(
                publication,
                status="retryable_failure",
                data={"failure_phase": "preflight", "last_error": str(exc)},
            )
            raise HTTPException(503, "Publication media could not be materialized") from exc
        repo.update(
            publication,
            status="uploading",
            data={"confirmation_consumed_at": consumed_at, "upload_started_at": consumed_at},
        )
        try:
            result = await asyncio.to_thread(
                upload_youtube_video,
                settings,
                file_path=local_path,
                title=publication.data["title"],
                description=publication.data.get("caption", ""),
                privacy=publication.data.get("privacy") or "private",
                tags=publication.data.get("hashtags", []),
                made_for_kids=bool(publication.data.get("made_for_kids")),
                contains_synthetic_media=bool(publication.data.get("synthetic_media_disclosure", True)),
                publish_at=publication.data.get("scheduled_at"),
                secret_ref=connection.data.get("secret_ref"),
            )
        except Exception as exc:
            repo.update(
                publication,
                status="retryable_failure",
                data={
                    "failure_phase": "remote_unknown",
                    "last_error": str(exc),
                    "manual_reconciliation_required": True,
                },
            )
            raise HTTPException(
                502,
                "YouTube upload outcome is unknown; retry is blocked until remote status is reconciled",
            ) from exc
        repo.update(
            publication,
            status="processing",
            data={**result, "upload_completed_at": datetime.now(UTC).isoformat()},
        )
        await _refresh_youtube_publication(repo, publication, settings)
    else:
        repo.update(
            publication,
            status="published",
            data={
                "confirmation_consumed_at": consumed_at,
                "external_post_id": f"mock_{publication.id}",
                "external_url": "https://www.youtube.com/",
                "published_at": datetime.now(UTC).isoformat(),
                "demo_data": True,
            },
        )
    if publication.status == "published":
        _ensure_publication_checkpoints(repo, publication)
    await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        event_type=f"publication.{publication.status}",
        resource_type="publication",
        resource_id=publication.id,
        correlation_id=str(publication.data.get("correlation_id") or publication.id),
    )
    return ResourceRepository.serialize(publication)


@router.get("/publications/{publication_id}", tags=["publishing"])
def get_publication(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("publications:read")
    return ResourceRepository.serialize(
        require_resource(ResourceRepository(session), publication_id, principal, kind="publication")
    )


@router.post("/publications/{publication_id}/refresh-status", tags=["publishing"])
async def refresh_publication_status(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("publications:read")
    repo = ResourceRepository(session)
    publication = require_resource(repo, publication_id, principal, kind="publication")
    if publication.data.get("platform") != "youtube" or settings.provider_mode != "live":
        return ResourceRepository.serialize(publication)
    await _refresh_youtube_publication(repo, publication, settings)
    return ResourceRepository.serialize(publication)


@router.post("/publications/{publication_id}/retry", tags=["publishing"])
async def retry_publication(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("publications:write")
    repo = ResourceRepository(session)
    publication = require_resource(repo, publication_id, principal, kind="publication")
    if publication.status in {"published", "processing", "uploading"}:
        if publication.data.get("external_post_id") and settings.provider_mode == "live":
            await _refresh_youtube_publication(repo, publication, settings)
        return ResourceRepository.serialize(publication)
    if publication.status != "retryable_failure":
        raise HTTPException(409, f"Publication in {publication.status} state cannot be retried")
    if publication.data.get("external_post_id"):
        await _refresh_youtube_publication(repo, publication, settings)
        return ResourceRepository.serialize(publication)
    if publication.data.get("failure_phase") != "preflight":
        raise HTTPException(
            409,
            "Retry is blocked because the remote upload outcome cannot be verified; reconcile the provider first",
        )
    project = require_project(repo, str(publication.project_id), principal)
    paused_reason = _publishing_is_paused(session, project, str(publication.data.get("platform")))
    if paused_reason:
        raise HTTPException(423, paused_reason)
    repo.update(
        publication,
        status="prepared",
        data={
            "retry_count": int(publication.data.get("retry_count", 0)) + 1,
            "retry_scheduled_at": datetime.now(UTC).isoformat(),
            "last_error": None,
        },
    )
    return ResourceRepository.serialize(publication)


@router.get("/publications/{publication_id}/export", tags=["publishing"])
def download_publication_export(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    principal.require("publications:read")
    repo = ResourceRepository(session)
    publication = require_resource(repo, publication_id, principal, kind="publication")
    asset = _create_publication_export(repo, publication, settings)
    local_path = Path(asset.data.get("local_path") or "")
    filename = f"{publication.id}-publication-package.zip"
    if local_path.is_file():
        return FileResponse(local_path, media_type="application/zip", filename=filename)
    public_path = str(asset.data.get("public_path") or "").removeprefix("/media/")
    remote = MediaStorage(settings).download_bytes(public_path)
    if not remote:
        raise HTTPException(404, "Export package is unavailable")
    body, _ = remote
    return Response(
        body,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/publications", tags=["publishing"])
def list_publications(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("publications:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id,
            project_id=project_id,
            kind="publication",
        )
    )


@router.post("/publications/{publication_id}/cancel", tags=["publishing"])
def cancel_publication(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("publications:write")
    repo = ResourceRepository(session)
    publication = require_resource(repo, publication_id, principal, kind="publication")
    if publication.status == "published":
        raise HTTPException(409, "Published content cannot be cancelled")
    return ResourceRepository.serialize(repo.update(publication, status="cancelled"))


@router.get("/projects/{project_id}/analytics/summary", tags=["analytics"])
def analytics_summary(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    repo = ResourceRepository(session)
    project = require_project(repo, project_id, principal)
    videos = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="video")
    jobs = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="generation_job")
    metrics = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="metric_snapshot")
    publications = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="publication")
    ideas = repo.list(organization_id=principal.organization_id, project_id=project_id, kind="idea")
    budget = project.data.get("settings", {}).get("budget", {"monthly_usd": 0, "used_usd": 0})
    return {
        "project_id": project_id,
        "period": "28d",
        "kpis": {
            "published": sum(1 for item in publications if item.status == "published"),
            "videos_ready": sum(1 for item in videos if item.status in {"approval_required", "approved"}),
            "awaiting_approval": sum(1 for item in videos if item.status == "approval_required"),
            "active_jobs": sum(1 for item in jobs if item.status in {"queued", "running"}),
            "idea_backlog": len(ideas),
            "budget_used_usd": budget.get("used_usd", 0),
            "budget_limit_usd": budget.get("monthly_usd", 0),
        },
        "latest_metrics": [ResourceRepository.serialize(item) for item in metrics[:5]],
        "patterns": [
            {"name": "Question hooks", "delta_percentile": 12.4, "confidence": 0.58, "sample_size": 7},
            {"name": "20–35 second explainers", "delta_percentile": 8.1, "confidence": 0.51, "sample_size": 6},
        ],
        "provider_comparison_warning": "Rates are normalized within platform/account cohorts; raw views are not compared across platforms.",
    }


@router.get("/projects/{project_id}/analytics/videos", tags=["analytics"])
def analytics_videos(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    require_project(ResourceRepository(session), project_id, principal)
    metrics = ResourceRepository(session).list(
        organization_id=principal.organization_id, project_id=project_id, kind="metric_snapshot"
    )
    return serialize_many(metrics)


@router.get("/publications/{publication_id}/metrics", tags=["analytics"])
def publication_metrics(
    publication_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    publication = require_resource(ResourceRepository(session), publication_id, principal, kind="publication")
    metrics = ResourceRepository(session).list(
        organization_id=principal.organization_id, project_id=publication.project_id, kind="metric_snapshot"
    )
    filtered = [item for item in metrics if item.data.get("publication_id") == publication_id]
    return serialize_many(filtered)


@router.get("/projects/{project_id}/metric-checkpoints", tags=["analytics"])
def metric_checkpoints(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id,
            project_id=project_id,
            kind="metric_checkpoint",
        )
    )


@router.post("/metric-checkpoints/{checkpoint_id}/collect", tags=["analytics"])
async def collect_metric_checkpoint(
    checkpoint_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("analytics:write")
    repo = ResourceRepository(session)
    checkpoint = require_resource(repo, checkpoint_id, principal, kind="metric_checkpoint")
    if checkpoint.status == "complete" and checkpoint.data.get("snapshot_id"):
        existing = repo.get(
            checkpoint.data["snapshot_id"],
            organization_id=principal.organization_id,
            kind="metric_snapshot",
        )
        if existing:
            return ResourceRepository.serialize(existing)
    publication = require_resource(
        repo,
        checkpoint.data["publication_id"],
        principal,
        kind="publication",
        project_id=checkpoint.project_id,
    )
    if publication.status != "published":
        raise HTTPException(409, "Metrics can only be collected for a published item")
    connection = repo.get_any(publication.data["connection_id"], kind="connection")
    if not connection or connection.organization_id != principal.organization_id:
        raise HTTPException(409, "Publication connection is unavailable")

    version = repo.get_any(str(publication.data.get("video_version_id") or ""), kind="video_version")
    video = repo.get_any(str(version.data.get("video_id") or ""), kind="video") if version else None
    script = repo.get_any(str(video.data.get("script_id") or ""), kind="script") if video else None
    job = repo.get_any(str(publication.data.get("generation_job_id") or ""), kind="generation_job")
    idea = repo.get_any(str(job.data.get("idea_id") or ""), kind="idea") if job else None
    script_data = dict(script.data.get("script") or {}) if script else {}
    content_features = {
        "hook": script_data.get("hook"),
        "format": idea.data.get("format") if idea else "educational_explainer",
        "topic": idea.data.get("title") if idea else publication.data.get("title"),
        "duration_seconds": round(float(version.data.get("duration_ms", 0)) / 1000, 2) if version else None,
        "cta": script_data.get("cta"),
        "aspect_ratio": version.data.get("aspect_ratio") if version else None,
        "visual_mode": "motion_graphics_hybrid",
    }

    published_at = datetime.fromisoformat(publication.data["published_at"])
    window = str(checkpoint.data["window"])
    repo.update(checkpoint, status="collecting", data={"attempted_at": datetime.now(UTC).isoformat()})
    if settings.provider_mode == "mock" or publication.data.get("demo_data"):
        result = mock_youtube_metrics(window=window, published_at=published_at)
    elif publication.data["platform"] == "youtube":
        result = await asyncio.to_thread(
            collect_youtube_metrics,
            settings,
            video_id=publication.data["external_post_id"],
            window=window,
            published_at=published_at,
            secret_ref=connection.data.get("secret_ref"),
        )
    else:
        raise HTTPException(409, "The provider metrics collector is not available")

    performance = observed_performance(result)
    snapshot = repo.add(
        kind="metric_snapshot",
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        status="complete" if result["is_complete"] else "partial",
        data={
            **result,
            **performance,
            "publication_id": publication.id,
            "platform": publication.data["platform"],
            "account_id": connection.data.get("external_account_id", "unknown"),
            "content_features": content_features,
        },
    )
    review = repo.add(
        kind="performance_review",
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        status="ready",
        data={
            "publication_id": publication.id,
            "metric_snapshot_id": snapshot.id,
            "window": window,
            **performance,
            "strengths": ["Retention signal is above the conservative baseline"]
            if performance["components"]["retention"] >= 65
            else [],
            "weaknesses": ["More account-level observations are required for a stable cohort"],
            "evidence": [snapshot.id],
            "content_features": content_features,
        },
    )
    strategies = repo.list(
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        kind="strategy",
    )
    next_version = max((int(item.data.get("strategy_version", 0)) for item in strategies), default=0) + 1
    strategy = repo.add(
        kind="strategy",
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        status="proposed",
        version=next_version,
        data={
            "strategy_version": next_version,
            "based_on_review_id": review.id,
            "recommendations": [
                "Keep the current short educational format while the cohort grows.",
                "Preserve a 20% exploration floor; do not optimize from one observation.",
            ],
            "confidence": performance["confidence"],
            "sample_size": performance["cohort_size"],
            "applied_automatically": False,
        },
    )
    repo.update(
        checkpoint,
        status="complete",
        data={"snapshot_id": snapshot.id, "review_id": review.id, "strategy_id": strategy.id},
    )
    sink = EventSink(settings)
    await sink.emit_metric_snapshot(
        organization_id=principal.organization_id,
        project_id=str(publication.project_id),
        publication_id=publication.id,
        platform=publication.data["platform"],
        account_id=connection.data.get("external_account_id", "unknown"),
        snapshot=result,
    )
    await sink.emit(
        session,
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        event_type="metrics.collected",
        resource_type="metric_snapshot",
        resource_id=snapshot.id,
        payload={"publication_id": publication.id, "window": window, "review_id": review.id},
    )
    return ResourceRepository.serialize(snapshot)


@router.post("/internal/metrics/collect-due", include_in_schema=False)
async def collect_due_metric_checkpoints(
    _identity: dict[str, Any] = Depends(require_google_service_identity),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    checkpoints = list(
        session.scalars(
            select(Resource).where(
                Resource.kind == "metric_checkpoint",
                Resource.status == "scheduled",
            )
        )
    )
    now = datetime.now(UTC)
    due = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.data.get("scheduled_at")
        and datetime.fromisoformat(checkpoint.data["scheduled_at"]) <= now
    ]
    collected: list[str] = []
    failed: list[dict[str, str]] = []
    for checkpoint in due[:25]:
        principal = Principal(
            actor_id="google_workflows_metrics",
            organization_id=checkpoint.organization_id,
            project_id=checkpoint.project_id,
            role="service_account",
            scopes=frozenset({"analytics:write"}),
        )
        try:
            snapshot = await collect_metric_checkpoint(
                checkpoint.id,
                principal=principal,
                session=session,
                settings=settings,
            )
            collected.append(str(snapshot["id"]))
        except Exception as exc:
            repo = ResourceRepository(session)
            delayed_id = checkpoint.data.get("delayed_snapshot_id")
            delayed = repo.get_any(str(delayed_id), kind="metric_snapshot") if delayed_id else None
            delayed_data = {
                "publication_id": checkpoint.data.get("publication_id"),
                "window": checkpoint.data.get("window"),
                "captured_at": datetime.now(UTC).isoformat(),
                "metrics": {},
                "availability": {"provider_metrics": "delayed"},
                "is_complete": False,
                "provider_api_versions": {"youtube_data": "v3", "youtube_analytics": "v2"},
                "last_error": str(exc),
            }
            if delayed:
                repo.update(delayed, status="delayed", data=delayed_data)
            else:
                delayed = repo.add(
                    kind="metric_snapshot",
                    organization_id=checkpoint.organization_id,
                    project_id=checkpoint.project_id,
                    status="delayed",
                    data=delayed_data,
                )
            repo.update(
                checkpoint,
                status="scheduled",
                data={
                    "attempts": int(checkpoint.data.get("attempts", 0)) + 1,
                    "last_error": str(exc),
                    "last_failed_at": datetime.now(UTC).isoformat(),
                    "delayed_snapshot_id": delayed.id,
                },
            )
            failed.append({"checkpoint_id": checkpoint.id, "error": str(exc)})
    return {"due": len(due), "collected": collected, "failed": failed}


@router.get("/projects/{project_id}/performance-reviews", tags=["analytics"])
def performance_reviews(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="performance_review"
        )
    )


@router.get("/projects/{project_id}/strategy", tags=["analytics"])
def get_active_strategy(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    require_project(ResourceRepository(session), project_id, principal)
    strategy = session.scalar(
        select(Resource).where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == project_id,
            Resource.kind == "strategy",
            Resource.status == "active",
        )
    )
    if not strategy:
        raise HTTPException(404, "Active strategy not found")
    return ResourceRepository.serialize(strategy)


@router.get("/projects/{project_id}/strategy/versions", tags=["analytics"])
def list_strategy_versions(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="strategy"
        )
    )


@router.post("/projects/{project_id}/strategy/{version_id}/activate", tags=["analytics"])
def activate_strategy(
    project_id: str,
    version_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("projects:write")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    target = require_resource(repo, version_id, principal, kind="strategy", project_id=project_id)
    if float(target.data.get("exploration_rate", 0.2)) < 0.1:
        raise HTTPException(409, "Exploration rate cannot be lower than 10%")
    for item in repo.list(organization_id=principal.organization_id, project_id=project_id, kind="strategy"):
        if item.status == "active":
            repo.update(item, status="superseded")
    return ResourceRepository.serialize(repo.update(target, status="active", data={"activated_at": datetime.now(UTC).isoformat()}))


@router.post("/projects/{project_id}/observability/smoke", tags=["developer"])
async def observability_smoke(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("integrations:write")
    require_project(ResourceRepository(session), project_id, principal)
    event = await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=project_id,
        event_type="observability.smoke",
        resource_type="project",
        resource_id=project_id,
        payload={"clickhouse": bool(settings.clickhouse_url), "pubsub": bool(settings.google_pubsub_topic)},
        correlation_id=ResourceRepository.new_id("trace"),
    )
    return {
        "status": "accepted",
        "event_id": event["event_id"],
        "clickhouse_configured": bool(settings.clickhouse_url),
        "pubsub_configured": bool(settings.google_pubsub_topic),
        "grafana_url": settings.grafana_url,
    }


@router.post("/projects/{project_id}/api-keys", status_code=201, tags=["developer"])
def create_api_key(
    project_id: str,
    payload: ApiKeyCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only Owner/Admin may create API keys")
    require_project(ResourceRepository(session), project_id, principal)
    invalid_scopes = sorted(set(payload.scopes) - set(ALL_SCOPES))
    if invalid_scopes or "admin" in payload.scopes:
        raise HTTPException(422, {"message": "API key scopes are invalid or too broad", "invalid_scopes": invalid_scopes})
    raw_key = f"avs_live_{secrets.token_urlsafe(30)}"
    record = ApiKeyRecord(
        id=ResourceRepository.new_id("key"),
        organization_id=principal.organization_id,
        project_id=project_id,
        name=payload.name,
        key_prefix=raw_key[:18],
        key_hash=hash_api_key(raw_key, settings.api_key_pepper),
        scopes=" ".join(sorted(set(payload.scopes))),
        expires_at=payload.expires_at,
    )
    session.add(record)
    session.commit()
    return {
        "id": record.id,
        "name": record.name,
        "key": raw_key,
        "key_prefix": record.key_prefix,
        "scopes": record.scopes.split(),
        "expires_at": record.expires_at,
        "warning": "This key is shown once. Store it in a secret manager.",
    }


@router.get("/projects/{project_id}/api-keys", tags=["developer"])
def list_api_keys(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(ResourceRepository(session), project_id, principal)
    records = list(
        session.scalars(
            select(ApiKeyRecord).where(
                ApiKeyRecord.organization_id == principal.organization_id,
                ApiKeyRecord.project_id == project_id,
            )
        )
    )
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "key_prefix": item.key_prefix,
                "scopes": item.scopes.split(),
                "expires_at": item.expires_at,
                "last_used_at": item.last_used_at,
                "revoked_at": item.revoked_at,
            }
            for item in records
        ],
        "next_cursor": None,
    }


@router.delete("/api-keys/{key_id}", status_code=204, tags=["developer"])
def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> Response:
    record = session.get(ApiKeyRecord, key_id)
    if not record or record.organization_id != principal.organization_id:
        raise HTTPException(404, "API key not found")
    record.revoked_at = datetime.now(UTC)
    session.add(record)
    session.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/webhooks", status_code=201, tags=["developer"])
def create_webhook(
    project_id: str,
    payload: WebhookCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    require_project(repo, project_id, principal)
    try:
        validate_public_url(str(payload.url), resolve_dns=False)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    webhook = repo.add(
        kind="webhook",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="active",
        data={"url": str(payload.url), "events": payload.events, "last_success_at": None, "delivery_count": 0},
    )
    return ResourceRepository.serialize(webhook)


@router.patch("/webhooks/{webhook_id}", tags=["developer"])
def patch_webhook(
    webhook_id: str,
    payload: WebhookPatch,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    webhook = require_resource(repo, webhook_id, principal, kind="webhook")
    changes = payload.model_dump(mode="json", exclude_none=True)
    status_value = changes.pop("status", None)
    if "url" in changes:
        try:
            validate_public_url(str(changes["url"]), resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return ResourceRepository.serialize(repo.update(webhook, status=status_value, data=changes))


@router.delete("/webhooks/{webhook_id}", status_code=204, tags=["developer"])
def delete_webhook(
    webhook_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> Response:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    webhook = require_resource(repo, webhook_id, principal, kind="webhook")
    repo.update(
        webhook,
        status="deleted",
        data={"deleted_at": datetime.now(UTC).isoformat(), "deleted_by": principal.actor_id},
    )
    return Response(status_code=204)


@router.get("/projects/{project_id}/webhooks", tags=["developer"])
def list_webhooks(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="webhook"
        )
    )


async def _deliver_webhook_attempt(
    repo: ResourceRepository,
    webhook: Resource,
    event: dict[str, Any],
    settings: Settings,
    *,
    delivery: Resource | None = None,
) -> Resource:
    raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(settings.webhook_signing_secret.encode(), raw, hashlib.sha256).hexdigest()
    attempt = int(delivery.data.get("attempt", 0)) + 1 if delivery else 1
    error = None
    try:
        validate_public_url(str(webhook.data["url"]), resolve_dns=settings.provider_mode != "mock")
        if settings.provider_mode == "mock":
            response_status = 202
        else:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(
                    webhook.data["url"],
                    content=raw,
                    headers={
                        "content-type": "application/json",
                        "x-avs-event-id": event["event_id"],
                        "x-avs-timestamp": str(event["timestamp"]),
                        "x-avs-signature": f"sha256={signature}",
                    },
                )
                response_status = response.status_code
    except Exception as exc:
        response_status = 0
        error = str(exc)
    delivered = 200 <= response_status < 300
    exhausted = not delivered and attempt >= 8
    state = "delivered" if delivered else ("failed" if exhausted else "retry_scheduled")
    details = {
        "webhook_id": webhook.id,
        "event_id": event["event_id"],
        "event": event,
        "response_status": response_status,
        "attempt": attempt,
        "signature": f"sha256={signature}",
        "error": error,
        "attempted_at": datetime.now(UTC).isoformat(),
        "next_attempt_at": (
            datetime.now(UTC) + timedelta(seconds=min(3600, 2 ** min(attempt, 10)))
        ).isoformat()
        if not delivered and not exhausted
        else None,
    }
    if delivery:
        repo.update(delivery, status=state, data=details)
    else:
        delivery = repo.add(
            kind="webhook_delivery",
            organization_id=webhook.organization_id,
            project_id=webhook.project_id,
            status=state,
            data=details,
        )
    if delivered:
        repo.update(
            webhook,
            data={
                "last_success_at": datetime.now(UTC).isoformat(),
                "delivery_count": int(webhook.data.get("delivery_count", 0)) + 1,
            },
        )
    return delivery


@router.post("/webhooks/{webhook_id}/test", tags=["developer"])
async def test_webhook(
    webhook_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    webhook = require_resource(repo, webhook_id, principal, kind="webhook")
    event = {
        "event_id": ResourceRepository.new_id("evt"),
        "type": "webhook.test",
        "timestamp": int(datetime.now(UTC).timestamp()),
        "project_id": webhook.project_id,
        "data": {"message": "Agentic Video Studio webhook test"},
    }
    delivery = await _deliver_webhook_attempt(repo, webhook, event, settings)
    return ResourceRepository.serialize(delivery)


@router.get("/webhooks/{webhook_id}/deliveries", tags=["developer"])
def list_webhook_deliveries(
    webhook_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    webhook = require_resource(repo, webhook_id, principal, kind="webhook")
    deliveries = repo.list(
        organization_id=principal.organization_id,
        project_id=webhook.project_id,
        kind="webhook_delivery",
        limit=200,
    )
    return serialize_many([item for item in deliveries if item.data.get("webhook_id") == webhook.id])


@router.post("/webhook-deliveries/{delivery_id}/replay", tags=["developer"])
async def replay_webhook_delivery(
    delivery_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    principal.require("webhooks:write")
    repo = ResourceRepository(session)
    delivery = require_resource(repo, delivery_id, principal, kind="webhook_delivery")
    webhook = require_resource(
        repo,
        str(delivery.data["webhook_id"]),
        principal,
        kind="webhook",
        project_id=delivery.project_id,
    )
    if webhook.status != "active":
        raise HTTPException(409, "Webhook is not active")
    updated = await _deliver_webhook_attempt(repo, webhook, dict(delivery.data["event"]), settings, delivery=delivery)
    return ResourceRepository.serialize(updated)


@router.post("/conversion-events", status_code=202, tags=["analytics"])
def create_conversion_event(
    payload: ConversionEventCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("analytics:read")
    repo = ResourceRepository(session)
    require_project(repo, payload.project_id, principal)
    require_resource(repo, payload.publication_id, principal, kind="publication", project_id=payload.project_id)
    existing = session.scalar(
        select(Resource).where(
            Resource.kind == "conversion_event",
            Resource.project_id == payload.project_id,
            Resource.data["event_id"].as_string() == payload.event_id,
        )
    )
    if existing:
        return {"conversion_event_id": existing.id, "status": "duplicate"}
    event = repo.add(
        kind="conversion_event",
        organization_id=principal.organization_id,
        project_id=payload.project_id,
        status="accepted",
        data=payload.model_dump(mode="json"),
    )
    return {"conversion_event_id": event.id, "status": "accepted"}


@router.get("/projects/{project_id}/audit-log", tags=["developer"])
def audit_log(
    project_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project(ResourceRepository(session), project_id, principal)
    return serialize_many(
        ResourceRepository(session).list(
            organization_id=principal.organization_id, project_id=project_id, kind="audit_event", limit=200
        )
    )


@router.get("/admin/alerts", tags=["admin"])
def list_operational_alerts(
    status_filter: str | None = Query(default="firing", alias="status"),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("admin")
    alerts = ResourceRepository(session).list(
        organization_id=principal.organization_id,
        kind="alert",
        statuses=(status_filter,) if status_filter else None,
        limit=200,
    )
    return serialize_many(alerts)
