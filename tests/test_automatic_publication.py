from __future__ import annotations

import pytest

from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.repository import ResourceRepository
from apps.api.app.workflow import WorkflowManager


@pytest.mark.asyncio
async def test_publish_automation_sends_youtube_and_queues_social_consent(client) -> None:
    del client  # The fixture starts the app lifespan and initializes the test database.
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        project = repo.add(
            kind="project",
            organization_id="org_demo",
            project_id=None,
            data={
                "name": "Automatic publishing fixture",
                "automation_mode": "publish",
                "context": {
                    "product_keywords": ["course creation"],
                    "problem_keywords": ["static lessons"],
                    "audience_interest_keywords": ["teacher tools"],
                },
                "settings": {"publishing": {"pause_all_publications": False}},
            },
        )
        project.project_id = project.id
        session.add(project)
        session.commit()
        video = repo.add(
            kind="video",
            organization_id="org_demo",
            project_id=project.id,
            status="approval_required",
            data={"title": "Automation fixture", "scene_ids": [], "versions": []},
        )
        job = repo.add(
            kind="generation_job",
            organization_id="org_demo",
            project_id=project.id,
            status="ready",
            data={
                "title": "Automation fixture",
                "automatic": True,
                "automatic_publish": True,
                "approval_mode": "final_only",
            },
        )
        version = repo.add(
            kind="video_version",
            organization_id="org_demo",
            project_id=project.id,
            status="approval_required",
            data={
                "video_id": video.id,
                "generation_job_id": job.id,
                "render_asset_id": "asset_not_needed_in_mock_mode",
                "aspect_ratio": "9:16",
            },
        )
        repo.add(
            kind="connection",
            organization_id="org_demo",
            project_id=project.id,
            status="active",
            data={"provider": "youtube", "display_name": "YouTube fixture"},
        )
        repo.add(
            kind="connection",
            organization_id="org_demo",
            project_id=project.id,
            status="active",
            data={"provider": "instagram", "display_name": "Instagram fixture"},
        )

        workflow = WorkflowManager(get_settings())
        await workflow._complete_automatic_publications(
            session,
            repo,
            job,
            [version.id],
            title="Automation fixture",
        )

        session.refresh(job)
        session.refresh(video)
        session.refresh(version)
        publications = repo.list(
            organization_id="org_demo",
            project_id=project.id,
            kind="publication",
            limit=20,
        )
        youtube = next(item for item in publications if item.data["platform"] == "youtube")
        instagram = next(item for item in publications if item.data["platform"] == "instagram")
        checkpoints = repo.list(
            organization_id="org_demo",
            project_id=project.id,
            kind="metric_checkpoint",
            limit=20,
        )

    assert version.status == "approved"
    assert video.status == "approved"
    assert youtube.status == "published"
    assert instagram.status == "awaiting_consent"
    assert instagram.data["automatic_consent_pending"] is True
    assert job.data["automatic_publication_status"] == "attention_required"
    assert set(job.data["automatic_publication_ids"]) == {youtube.id, instagram.id}
    assert {item.data["window"] for item in checkpoints if item.data["publication_id"] == youtube.id} == {
        "24h",
        "7d",
    }
