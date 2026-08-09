from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

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
from sqlalchemy import select
from sqlalchemy.orm import Session

from .cloud_auth import require_google_service_identity
from .config import Settings, get_settings
from .database import SessionLocal, get_db
from .events import EventSink
from .metrics import collect_youtube_metrics, mock_youtube_metrics, observed_performance
from .models import ApiKeyRecord, Resource
from .providers import ParallelSearchProvider
from .publishing import (
    PROVIDER_CAPABILITIES,
    confirmation_token,
    exchange_youtube_code,
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
    ProjectCreate,
    ProjectPatch,
    PublicationConfirm,
    PublicationCreate,
    ResearchRunCreate,
    ReviewAction,
    SceneRegenerate,
    SourceCreate,
    SourceItemCreate,
    WebhookCreate,
)
from .security import Principal, get_principal, validate_public_url
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
        changes["settings"] = {**project.data.get("settings", {}), **changes["settings"]}
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
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    source = require_resource(repo, source_id, principal, kind="source")
    allowed = {key: value for key, value in payload.items() if key in {"name", "config", "status", "generation_policy"}}
    status_value = allowed.pop("status", None)
    return ResourceRepository.serialize(repo.update(source, data=allowed, status=status_value))


@router.delete("/sources/{source_id}", status_code=204, tags=["sources"])
def delete_source(
    source_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> Response:
    principal.require("sources:write")
    repo = ResourceRepository(session)
    source = require_resource(repo, source_id, principal, kind="source")
    repo.update(source, status="deleted", data={"deleted_at": datetime.now(UTC).isoformat()})
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
    duplicate = session.scalar(
        select(Resource).where(
            Resource.organization_id == principal.organization_id,
            Resource.project_id == project_id,
            Resource.kind == "source_item",
            Resource.data["content_hash"].as_string() == content_hash,
        )
    )
    if duplicate:
        return duplicate, True
    item = repo.add(
        kind="source_item",
        organization_id=principal.organization_id,
        project_id=project_id,
        status="accepted",
        data={**body, "content_hash": content_hash, "duplicate_status": "unique", "rights_status": "confirmed"},
    )
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
def create_source_item(
    project_id: str,
    payload: SourceItemCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("sources:write")
    item, duplicate = _create_source_item(
        project_id=project_id,
        body=payload.model_dump(mode="json"),
        principal=principal,
        session=session,
        idempotency_key=idempotency_key,
        endpoint=f"POST:/v1/projects/{project_id}/source-items",
    )
    return {
        "source_item_id": item.id,
        "status": item.status,
        "duplicate": duplicate,
        "links": {"self": f"/v1/source-items/{item.id}"},
    }


@router.post("/content-items", status_code=202, tags=["sources"])
def create_content_item(
    payload: ContentItemCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
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
    item, duplicate = _create_source_item(
        project_id=payload.project_id,
        body=body,
        principal=principal,
        session=session,
        idempotency_key=idempotency_key,
        endpoint="POST:/v1/content-items",
    )
    return {"source_item_id": item.id, "status": item.status, "duplicate": duplicate}


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
                    "sources": packet.sources,
                    "claims": packet.claims,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
            score = min(92, 61 + len(packet.sources) * 7)
            for index in range(min(int(run.data.get("max_candidates", 5)), 3)):
                repo.add(
                    kind="topic_candidate",
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    status="candidate",
                    data={
                        "research_run_id": run.id,
                        "title": (
                            "One lesson, three reusable learning assets",
                            "The feedback loop most course creators skip",
                            "A 30-second fix for an unclear course outcome",
                        )[index],
                        "angle": (
                            "Show the three-part transformation with one concrete example",
                            "Contrast late generic feedback with immediate actionable practice",
                            "Rewrite a vague topic as a measurable learner outcome",
                        )[index],
                        "audience": "Independent teachers",
                        "why_now": "Relevant to active creator workflows and current short-form discovery.",
                        "source_ids": [source["id"] for source in packet.sources],
                        "topic_opportunity_score": score - index * 5,
                        "score_confidence": min(0.86, 0.48 + len(packet.sources) * 0.08),
                        "risk_flags": [],
                        "freshness_expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    },
                )
        except Exception as exc:
            repo.update(run, status="failed", data={"error": str(exc), "retryable": True})


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
    return ResourceRepository.serialize(repo.update(candidate, status="selected"))


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
        },
    )
    repo.update(idea, status="planned")
    return ResourceRepository.serialize(item)


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
        "min": round(0.8 * len(payload.aspect_ratios), 2),
        "max": round(4.2 * len(payload.aspect_ratios), 2),
    }
    if estimated["max"] > payload.max_cost_usd:
        raise HTTPException(409, "Estimated generation cost exceeds max_cost_usd")
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


@router.post("/publications", status_code=202, tags=["publishing"])
def prepare_publication(
    payload: PublicationCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require("publications:write")
    repo = ResourceRepository(session)
    version = require_resource(repo, payload.video_version_id, principal, kind="video_version")
    if version.status != "approved" and not payload.dry_run:
        raise HTTPException(409, "Video version must be approved before publication")
    if payload.connection_id.startswith("unconfigured_"):
        connection = None
    else:
        connection = require_resource(repo, payload.connection_id, principal, kind="connection")
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
    token = confirmation_token()
    requires_consent = bool(capabilities.get("requires_per_post_consent"))
    warnings = []
    if payload.platform in {"instagram", "tiktok"}:
        warnings.append("Official production publishing access is not active; export/draft fallback will be used.")
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
    expected = publication.data.get("confirmation_token_hash", "")
    actual = hashlib.sha256(payload.confirmation_token.encode()).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(403, "Invalid confirmation token")
    if publication.data.get("consent_required") and not payload.explicit_consent:
        raise HTTPException(409, "Explicit per-post consent is required by this provider")
    platform = publication.data["platform"]
    if platform == "tiktok":
        repo.update(
            publication,
            status="export_ready",
            data={"consent_received_at": datetime.now(UTC).isoformat(), "fallback": "creator_finishes_in_tiktok"},
        )
    elif platform in {"instagram", "export"}:
        repo.update(publication, status="export_ready", data={"fallback": "download_package"})
    elif platform == "youtube" and settings.provider_mode == "live":
        version = repo.get_any(publication.data["video_version_id"], kind="video_version")
        asset = repo.get_any(version.data["render_asset_id"], kind="media_asset") if version else None
        connection = repo.get_any(publication.data["connection_id"], kind="connection")
        if not version or not asset or not connection:
            raise HTTPException(409, "Publication media or connection is unavailable")
        repo.update(publication, status="uploading")
        storage = MediaStorage(settings)
        local_path = Path(asset.data.get("local_path") or asset.data["storage_uri"])
        storage.materialize(storage_uri=asset.data.get("storage_uri"), local_path=local_path)
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
        repo.update(publication, status="published", data={**result, "published_at": datetime.now(UTC).isoformat()})
    else:
        repo.update(
            publication,
            status="published",
            data={
                "external_post_id": f"mock_{publication.id}",
                "external_url": "https://www.youtube.com/",
                "published_at": datetime.now(UTC).isoformat(),
                "demo_data": True,
            },
        )
    if publication.status == "published":
        for window, delta in (("24h", timedelta(hours=24)), ("7d", timedelta(days=7))):
            repo.add(
                kind="metric_checkpoint",
                organization_id=principal.organization_id,
                project_id=publication.project_id,
                status="scheduled",
                data={
                    "publication_id": publication.id,
                    "window": window,
                    "scheduled_at": (datetime.now(UTC) + delta).isoformat(),
                },
            )
    await EventSink(settings).emit(
        session,
        organization_id=principal.organization_id,
        project_id=publication.project_id,
        event_type=f"publication.{publication.status}",
        resource_type="publication",
        resource_id=publication.id,
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
            ResourceRepository(session).update(
                checkpoint,
                status="scheduled",
                data={
                    "attempts": int(checkpoint.data.get("attempts", 0)) + 1,
                    "last_error": str(exc),
                    "last_failed_at": datetime.now(UTC).isoformat(),
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
    raw = json.dumps(event, separators=(",", ":")).encode()
    signature = hmac.new(settings.webhook_signing_secret.encode(), raw, hashlib.sha256).hexdigest()
    if settings.provider_mode == "mock":
        response_status = 202
    else:
        async with httpx.AsyncClient(timeout=10) as client:
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
    delivery = repo.add(
        kind="webhook_delivery",
        organization_id=principal.organization_id,
        project_id=webhook.project_id,
        status="delivered" if 200 <= response_status < 300 else "retry_scheduled",
        data={
            "webhook_id": webhook.id,
            "event_id": event["event_id"],
            "response_status": response_status,
            "attempt": 1,
            "signature": f"sha256={signature}",
        },
    )
    return ResourceRepository.serialize(delivery)


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
