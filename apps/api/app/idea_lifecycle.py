"""Project-scoped idea stages derived from actual production and publication state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Resource

VIDEO_STAGES = {"scene_generation", "voice_audio", "render", "qa", "scoring", "completed"}


def idea_status(session: Session, idea: Resource) -> str:
    job_id = idea.data.get("generation_job_id")
    job = session.get(Resource, job_id) if job_id else None
    if (
        not job
        or job.kind != "generation_job"
        or (job.organization_id, job.project_id) != (idea.organization_id, idea.project_id)
    ):
        return "selected"
    if job.status not in {"ready", "cancelled"}:
        return "video_generation" if job.data.get("current_stage") in VIDEO_STAGES else "script_generation"
    video = session.get(Resource, job.data.get("video_id")) if job.data.get("video_id") else None
    if (
        not video
        or video.kind != "video"
        or (video.organization_id, video.project_id) != (idea.organization_id, idea.project_id)
    ):
        return "selected" if job.status == "cancelled" else "video_ready"
    current_versions = job.data.get("video_version_ids") or [str(video.data.get("latest_version_id") or "")]
    published = session.scalar(
        select(Resource.id)
        .where(
            Resource.kind == "publication",
            Resource.organization_id == idea.organization_id,
            Resource.project_id == idea.project_id,
            Resource.status == "published",
            Resource.data["video_version_id"].as_string().in_(current_versions),
        )
        .limit(1)
    )
    return "published" if published else "video_ready"


def sync_idea_lifecycle(session: Session, changed: Resource) -> None:
    if changed.kind not in {"idea", "generation_job", "publication", "video"}:
        return
    session.flush()
    statement = select(Resource).where(
        Resource.kind == "idea",
        Resource.organization_id == changed.organization_id,
        Resource.project_id == changed.project_id,
    )
    if changed.kind == "generation_job":
        statement = statement.where(Resource.data["generation_job_id"].as_string() == changed.id)
    ideas = [changed] if changed.kind == "idea" else session.scalars(statement).all()
    for idea in ideas:
        status = idea_status(session, idea)
        if idea.status != status:
            idea.status = status
            idea.updated_at = datetime.now(UTC)
