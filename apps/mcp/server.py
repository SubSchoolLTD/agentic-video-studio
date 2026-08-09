from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .utils import stable_idempotency_key

mcp = FastMCP("Agentic Video Studio", stateless_http=True, json_response=True)
API_BASE = os.getenv("APP_BASE_URL", "http://localhost:8000")
TOKEN = os.getenv("APP_DEMO_TOKEN", "demo-token")
async def api(method: str, path: str, *, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    request_headers = {"Authorization": f"Bearer {TOKEN}", **(headers or {})}
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
async def topic_candidate_list(project_id: str) -> dict[str, Any]:
    """List ranked topic candidates."""
    return await api("GET", f"/v1/projects/{project_id}/topic-candidates")


@mcp.tool()
async def idea_create(project_id: str, title: str, audience: str, hook: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Create a content idea for a single audience."""
    payload = {"title": title, "audience": audience, "hook": hook, "objective": "education"}
    if dry_run:
        return {"dry_run": True, "action": "idea_create", "payload": payload}
    return await api("POST", f"/v1/projects/{project_id}/ideas", json=payload)


@mcp.tool()
async def generation_start(
    project_id: str,
    title: str,
    aspect_ratios: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Start the durable production workflow or calculate its plan/cost."""
    payload = {"title": title, "aspect_ratios": aspect_ratios or ["9:16"], "target_duration_seconds": 30}
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
async def video_get(video_id: str) -> dict[str, Any]:
    """Get video versions, scenes, QA, and score reports."""
    return await api("GET", f"/v1/videos/{video_id}")


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


@mcp.resource("project://{project_id}/brand-profile")
async def project_brand_profile(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/brand-profile"), indent=2)


@mcp.resource("project://{project_id}/active-strategy")
async def project_active_strategy(project_id: str) -> str:
    return json.dumps(await api("GET", f"/v1/projects/{project_id}/strategy"), indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
