from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from starlette.middleware.authentication import AuthenticationMiddleware

from apps.api.app.auth import decode_access_token
from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.models import User
from apps.api.app.repository import find_api_key

from .utils import stable_idempotency_key

mcp = FastMCP(
    "Framewise",
    instructions=(
        "Manage one tenant-scoped Framewise project through the same permission checks as the web application. "
        "Inspect current state before writes, use dry_run where offered, and never request or expose social credentials."
    ),
    website_url="https://studio.subschool.us",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
)
API_BASE = os.getenv("MCP_API_BASE") or os.getenv("APP_BASE_URL", "http://localhost:8000")
TOKEN = os.getenv("APP_API_TOKEN", "").strip()


class FramewiseTokenVerifier:
    """Validate the same JWTs and project-scoped API keys accepted by REST."""

    async def verify_token(self, token: str) -> AccessToken | None:
        settings = get_settings()
        if settings.app_auth_mode == "demo" and token == settings.app_demo_token:
            return AccessToken(token=token, client_id="demo", scopes=["mcp"], subject="user_demo_owner")
        with SessionLocal() as session:
            try:
                claims = decode_access_token(token, settings)
            except jwt.PyJWTError:
                claims = None
            if claims:
                user = session.get(User, str(claims.get("sub") or ""))
                if (
                    user
                    and user.status == "active"
                    and user.email_verified_at is not None
                    and int(claims.get("ver", 0)) == user.token_version
                ):
                    expires_at = claims.get("exp")
                    if isinstance(expires_at, datetime):
                        expires_at = int(expires_at.replace(tzinfo=expires_at.tzinfo or UTC).timestamp())
                    return AccessToken(
                        token=token,
                        client_id=user.id,
                        subject=user.id,
                        scopes=["mcp"],
                        expires_at=int(expires_at) if expires_at else None,
                        claims={"organization_id": claims.get("org"), "credential_type": "session"},
                    )
            record = find_api_key(session, token, settings.api_key_pepper)
            if not record:
                return None
            return AccessToken(
                token=token,
                client_id=record.id,
                subject=record.id,
                scopes=["mcp", *record.scopes.split()],
                claims={
                    "organization_id": record.organization_id,
                    "project_id": record.project_id,
                    "credential_type": "api_key",
                },
            )


def request_token() -> str:
    access_token = get_access_token()
    return access_token.token if access_token else TOKEN


async def api(method: str, path: str, *, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    token = request_token()
    if not token:
        raise RuntimeError("APP_API_TOKEN must contain a tenant-scoped API key or access token")
    request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60) as client:
        response = await client.request(method, path, json=json, headers=request_headers)
        response.raise_for_status()
        return response.json() if response.content else None


@mcp.tool()
async def project_list() -> dict[str, Any]:
    """List projects visible to the scoped MCP principal."""
    return await api("GET", "/v1/projects")


@mcp.tool()
async def project_get(project_id: str) -> dict[str, Any]:
    """Get a project and its current state."""
    return await api("GET", f"/v1/projects/{project_id}")


@mcp.tool()
async def project_update_brief(project_id: str, settings: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """Update project settings, or describe the change without side effects."""
    if dry_run:
        return {"dry_run": True, "action": "patch_project", "project_id": project_id, "settings": settings}
    return await api("PATCH", f"/v1/projects/{project_id}", json={"settings": settings})


@mcp.tool()
async def project_update_context(
    project_id: str,
    product_essence: str,
    target_audience_summary: str,
    problem_statement: str,
    solution_summary: str,
    product_keywords: list[str] | None = None,
    problem_keywords: list[str] | None = None,
    audience_interest_keywords: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update the confirmed project context used by research and editorial generation."""
    project_context = {
        "product_essence": product_essence,
        "target_audience_summary": target_audience_summary,
        "problem_statement": problem_statement,
        "solution_summary": solution_summary,
        "product_keywords": product_keywords or [],
        "problem_keywords": problem_keywords or [],
        "audience_interest_keywords": audience_interest_keywords or [],
    }
    if dry_run:
        return {"dry_run": True, "action": "project_update_context", "project_context": project_context}
    return await api(
        "PATCH",
        f"/v1/projects/{project_id}/brand-profile",
        json={"project_context": project_context, "confirmed": True},
    )


@mcp.tool()
async def automation_get(project_id: str) -> dict[str, Any]:
    """Read automation mode, cadence, content mix, video defaults, budget readiness and funding state."""
    return await api("GET", f"/v1/projects/{project_id}/automation")


@mcp.tool()
async def automation_configure(
    project_id: str,
    mode: str,
    videos_per_week: int = 3,
    average_duration_seconds: int = 30,
    audio_quality: str = "premium",
    selling_percent: int = 20,
    viral_percent: int = 30,
    informative_percent: int = 50,
    research_interval_hours: int = 24,
    research_recency_days: int = 30,
    research_max_candidates: int = 50,
    research_backlog_target: int = 150,
    video_defaults: dict[str, dict[str, Any]] | None = None,
    publishing: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Configure the same automation controls exposed in onboarding and project settings."""
    payload = {
        "mode": mode,
        "videos_per_week": videos_per_week,
        "average_duration_seconds": average_duration_seconds,
        "audio_quality": audio_quality,
        "selling_percent": selling_percent,
        "viral_percent": viral_percent,
        "informative_percent": informative_percent,
        "research_interval_hours": research_interval_hours,
        "research_recency_days": research_recency_days,
        "research_max_candidates": research_max_candidates,
        "research_backlog_target": research_backlog_target,
        "video_defaults": video_defaults,
        "publishing": publishing,
    }
    if dry_run:
        return {
            "dry_run": True,
            "action": "automation_configure",
            "project_id": project_id,
            "payload": payload,
            "content_mix_total": selling_percent + viral_percent + informative_percent,
        }
    return await api("PUT", f"/v1/projects/{project_id}/automation", json=payload)


@mcp.tool()
async def automation_activate(project_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Activate configured automation and resume budget-blocked work after a top-up."""
    if dry_run:
        return {"dry_run": True, "action": "automation_activate", "project_id": project_id}
    return await api("POST", f"/v1/projects/{project_id}/automation/activate")


@mcp.tool()
async def source_add_text(
    project_id: str,
    title: str,
    content_markdown: str,
    rights_confirmed: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add owned text as a normalized source item."""
    payload = {
        "source_type": "text",
        "title": title,
        "content_markdown": content_markdown,
        "rights_confirmed": rights_confirmed,
        "language": "en",
    }
    if dry_run:
        return {"dry_run": True, "action": "source_add_text", "payload": payload}
    return await api(
        "POST",
        f"/v1/projects/{project_id}/source-items",
        json=payload,
        headers={"Idempotency-Key": stable_idempotency_key("mcp-source", project_id, title, content_markdown)},
    )


@mcp.tool()
async def source_add_url(
    project_id: str,
    title: str,
    url: str,
    rights_confirmed: bool,
    run_research: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a public URL as a source and optionally research it."""
    payload = {
        "source_type": "url",
        "title": title,
        "canonical_url": url,
        "rights_confirmed": rights_confirmed,
        "language": "en",
        "processing": {"research": "required" if run_research else False},
    }
    if dry_run:
        return {"dry_run": True, "action": "source_add_url", "payload": payload}
    return await api(
        "POST",
        f"/v1/projects/{project_id}/source-items",
        json=payload,
        headers={"Idempotency-Key": stable_idempotency_key("mcp-url", project_id, title, url)},
    )


@mcp.tool()
async def source_list(project_id: str) -> dict[str, Any]:
    """List configured project sources."""
    return await api("GET", f"/v1/projects/{project_id}/sources")


@mcp.tool()
async def source_item_list(project_id: str) -> dict[str, Any]:
    """List normalized text, URL and owned-content items available to research."""
    return await api("GET", f"/v1/projects/{project_id}/source-items")


@mcp.tool()
async def research_run(project_id: str, objective: str, dry_run: bool = False) -> dict[str, Any]:
    """Start evidence-backed Parallel research."""
    if dry_run:
        return {"dry_run": True, "provider": "parallel", "objective": objective, "estimated_calls": 1}
    return await api("POST", f"/v1/projects/{project_id}/research-runs", json={"objective": objective})


@mcp.tool()
async def research_get_status(run_id: str) -> dict[str, Any]:
    """Get a research run, evidence records, and candidates."""
    return await api("GET", f"/v1/research-runs/{run_id}")


@mcp.tool()
async def research_feedback_get(project_id: str) -> dict[str, Any]:
    """Read the selected, hidden and published-performance signals used by the next research run."""
    return await api("GET", f"/v1/projects/{project_id}/research-feedback")


@mcp.tool()
async def topic_candidate_list(project_id: str) -> dict[str, Any]:
    """List ranked topic candidates."""
    return await api("GET", f"/v1/projects/{project_id}/topic-candidates")


@mcp.tool()
async def topic_candidate_select(candidate_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Convert a research candidate into an idea and record a positive preference signal."""
    if dry_run:
        return {"dry_run": True, "action": "topic_candidate_select", "candidate_id": candidate_id}
    return await api("POST", f"/v1/topic-candidates/{candidate_id}/select")


@mcp.tool()
async def topic_candidate_reject(
    candidate_id: str,
    reason: str = "Not a fit for the current content strategy",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Hide a candidate and record a bounded negative preference signal."""
    if dry_run:
        return {"dry_run": True, "action": "topic_candidate_reject", "candidate_id": candidate_id, "reason": reason}
    return await api("POST", f"/v1/topic-candidates/{candidate_id}/reject", json={"comment": reason})


@mcp.tool()
async def idea_create(
    project_id: str,
    title: str,
    audience: str,
    hook: str = "",
    objective: str = "awareness",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a content idea for a single audience."""
    payload = {"title": title, "audience": audience, "hook": hook, "objective": objective}
    if dry_run:
        return {"dry_run": True, "action": "idea_create", "payload": payload}
    return await api("POST", f"/v1/projects/{project_id}/ideas", json=payload)


@mcp.tool()
async def idea_list(project_id: str) -> dict[str, Any]:
    """List project ideas and their production links."""
    return await api("GET", f"/v1/projects/{project_id}/ideas")


@mcp.tool()
async def generation_start(
    project_id: str,
    title: str,
    idea_id: str = "",
    aspect_ratios: list[str] | None = None,
    visual_mode: str = "ugc_creator",
    audio_mode: str = "veo_native",
    target_duration_seconds: int = 30,
    generation_start_mode: str = "immediate",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Start the durable production workflow or calculate its plan/cost."""
    payload = {
        "title": title,
        "idea_id": idea_id or None,
        "aspect_ratios": aspect_ratios or ["9:16"],
        "visual_mode": visual_mode,
        "audio_mode": audio_mode,
        "target_duration_seconds": target_duration_seconds,
        "generation_start_mode": generation_start_mode,
    }
    if dry_run:
        return {"dry_run": True, "action": "generation_start", "estimated_cost": {"min": 0.8, "max": 4.2}, "payload": payload}
    return await api(
        "POST",
        f"/v1/projects/{project_id}/generation-jobs",
        json=payload,
        headers={"Idempotency-Key": stable_idempotency_key("mcp-generation", project_id, title)},
    )


@mcp.tool()
async def generation_get_status(job_id: str) -> dict[str, Any]:
    """Get stage-level generation status and partial artifacts."""
    return await api("GET", f"/v1/generation-jobs/{job_id}")


@mcp.tool()
async def generation_list(project_id: str) -> dict[str, Any]:
    """List generation jobs including partial, failed and budget-blocked work."""
    return await api("GET", f"/v1/projects/{project_id}/generation-jobs")


@mcp.tool()
async def generation_retry(job_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Resume a failed generation from its latest durable checkpoint."""
    if dry_run:
        return {"dry_run": True, "action": "generation_retry", "job_id": job_id}
    return await api("POST", f"/v1/generation-jobs/{job_id}/retry")


@mcp.tool()
async def generation_cancel(job_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Cancel a generation without deleting completed immutable artifacts."""
    if dry_run:
        return {"dry_run": True, "action": "generation_cancel", "job_id": job_id}
    return await api("POST", f"/v1/generation-jobs/{job_id}/cancel")


@mcp.tool()
async def video_get(video_id: str) -> dict[str, Any]:
    """Get video versions, scenes, QA, and score reports."""
    return await api("GET", f"/v1/videos/{video_id}")


@mcp.tool()
async def video_list(project_id: str) -> dict[str, Any]:
    """List completed and in-review videos for a project."""
    return await api("GET", f"/v1/projects/{project_id}/videos")


@mcp.tool()
async def video_approve(video_version_id: str, comment: str = "Approved through MCP", dry_run: bool = False) -> dict[str, Any]:
    """Approve a video version; hard gates remain non-overridable."""
    if dry_run:
        return {"dry_run": True, "action": "video_approve", "video_version_id": video_version_id}
    return await api("POST", f"/v1/video-versions/{video_version_id}/approve", json={"comment": comment})


@mcp.tool()
async def publication_prepare(
    video_version_id: str,
    connection_id: str,
    platform: str,
    title: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prepare a publication plan. This never silently commits a post."""
    return await api(
        "POST",
        "/v1/publications",
        json={
            "video_version_id": video_version_id,
            "connection_id": connection_id,
            "platform": platform,
            "title": title,
            "dry_run": dry_run,
        },
    )


@mcp.tool()
async def publication_commit(plan_id: str, confirmation_token: str, explicit_consent: bool = False) -> dict[str, Any]:
    """Commit a prepared publication. TikTok always requires explicit consent."""
    return await api(
        "POST",
        f"/v1/publications/{plan_id}/confirm",
        json={"confirmation_token": confirmation_token, "explicit_consent": explicit_consent},
    )


@mcp.tool()
async def analytics_get_summary(project_id: str) -> dict[str, Any]:
    """Get normalized analytics, confidence, and current patterns."""
    return await api("GET", f"/v1/projects/{project_id}/analytics/summary")


@mcp.tool()
async def strategy_get_active(project_id: str) -> dict[str, Any]:
    """Get the active bounded strategy version."""
    return await api("GET", f"/v1/projects/{project_id}/strategy")


@mcp.tool()
async def strategy_get_proposals(project_id: str) -> dict[str, Any]:
    """List active, proposed and superseded strategy versions derived from measured performance."""
    return await api("GET", f"/v1/projects/{project_id}/strategy/versions")


@mcp.tool()
async def strategy_activate(project_id: str, version_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Activate a proposed strategy without weakening system exploration or safety floors."""
    if dry_run:
        return {"dry_run": True, "action": "strategy_activate", "project_id": project_id, "version_id": version_id}
    return await api("POST", f"/v1/projects/{project_id}/strategy/{version_id}/activate")


@mcp.tool()
async def calendar_get(project_id: str) -> dict[str, Any]:
    """Get planned research, production, publication and metric-checkpoint work."""
    return await api("GET", f"/v1/projects/{project_id}/calendar")


@mcp.resource("project://{project_id}/brand-profile")
async def project_brand_profile(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/brand-profile"), indent=2)


@mcp.resource("project://{project_id}/active-strategy")
async def project_active_strategy(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/strategy"), indent=2)


@mcp.resource("project://{project_id}/automation")
async def project_automation(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/automation"), indent=2)


@mcp.resource("project://{project_id}/calendar")
async def project_calendar(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/calendar"), indent=2)


@mcp.resource("project://{project_id}/performance-feedback")
async def project_performance_feedback(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/research-feedback"), indent=2)


_mcp_starlette_app = mcp.streamable_http_app()
mcp_http_app = AuthenticationMiddleware(
    AuthContextMiddleware(RequireAuthMiddleware(_mcp_starlette_app, required_scopes=[])),
    backend=BearerAuthBackend(FramewiseTokenVerifier()),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(mcp_http_app, host=os.getenv("MCP_HOST", "127.0.0.1"), port=int(os.getenv("MCP_PORT", "8001")))
