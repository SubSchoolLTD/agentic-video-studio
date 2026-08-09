from __future__ import annotations

import asyncio
import time

from sqlalchemy import func, select

from apps.api.app import workflow
from apps.api.app.database import SessionLocal
from apps.api.app.models import Resource
from apps.api.app.renderer import RenderError


def wait_for_job(client, job_id: str, headers: dict[str, str], timeout: float = 35) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/generation-jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"ready", "failed", "blocked"}:
            return job
        time.sleep(0.15)
    raise AssertionError(f"Job {job_id} did not complete before timeout")


def test_mock_source_to_render_to_publication(client, auth_headers) -> None:
    idea = client.post(
        "/v1/projects/prj_subschool/ideas",
        json={
            "title": "Turn one lesson into a reusable course",
            "hook": "One lesson can do more than you think.",
            "audience": "Independent teachers",
            "objective": "education",
        },
        headers=auth_headers,
    )
    assert idea.status_code == 201
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "idea_id": idea.json()["id"],
            "aspect_ratios": ["9:16", "16:9"],
            "target_duration_seconds": 8,
            "approval_mode": "final_only",
            "variants": 3,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-e2e-1"},
    )
    assert created.status_code == 202
    job = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    assert job["progress"] == 1
    assert all(stage["status"] == "completed" for stage in job["stages"])
    script_stage = next(stage for stage in job["stages"] if stage["name"] == "script")
    assert script_stage["output"]["variant_count"] == 3
    assert len(script_stage["output"]["script_ids"]) == 3

    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers)
    assert video.status_code == 200
    body = video.json()
    assert len(body["versions"]) == 2
    assert {item["aspect_ratio"] for item in body["versions"]} == {"9:16", "16:9"}
    assert body["qa_report"]["hard_gate_passed"] is True
    assert body["score_report"]["publish_readiness"] >= 70
    assert body["score_report"]["confidence"] < 0.65

    version = body["versions"][0]
    media = client.get(version["render_url"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "video/mp4"
    assert len(media.content) > 10_000

    approval = client.post(
        f"/v1/video-versions/{version['id']}/approve",
        json={"comment": "Mock e2e review passed"},
        headers=auth_headers,
    )
    assert approval.status_code == 200
    locked_scene = body["scenes"][0]
    regeneration = client.post(
        f"/v1/scenes/{locked_scene['id']}/regenerate",
        json={"reason": "Approval must lock this scene"},
        headers=auth_headers,
    )
    assert regeneration.status_code == 409
    refreshed_video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers)
    assert refreshed_video.json()["versions"][0]["status"] == "approved"
    prepared = client.post(
        "/v1/publications",
        json={
            "video_version_id": version["id"],
            "connection_id": "conn_youtube_demo",
            "platform": "youtube",
            "title": "One lesson, three reusable assets",
            "caption": "Evidence-backed mock e2e publication.",
            "privacy": "private",
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-publication-1"},
    )
    assert prepared.status_code == 202
    committed = client.post(
        f"/v1/publications/{prepared.json()['publication_id']}/confirm",
        json={"confirmation_token": prepared.json()["confirmation_token"]},
        headers=auth_headers,
    )
    assert committed.status_code == 200
    assert committed.json()["status"] == "published"
    assert committed.json()["demo_data"] is True

    checkpoints = client.get(
        "/v1/projects/prj_subschool/metric-checkpoints", headers=auth_headers
    )
    assert checkpoints.status_code == 200
    publication_checkpoints = [
        item
        for item in checkpoints.json()["items"]
        if item["publication_id"] == prepared.json()["publication_id"]
    ]
    assert {item["window"] for item in publication_checkpoints} == {"24h", "7d"}
    early = next(item for item in publication_checkpoints if item["window"] == "24h")
    collected = client.post(
        f"/v1/metric-checkpoints/{early['id']}/collect", headers=auth_headers
    )
    assert collected.status_code == 200
    assert collected.json()["availability"]["views"] == "synthetic_demo"
    assert collected.json()["observed_performance_index"] > 0
    repeated = client.post(
        f"/v1/metric-checkpoints/{early['id']}/collect", headers=auth_headers
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == collected.json()["id"]

    reviews = client.get(
        "/v1/projects/prj_subschool/performance-reviews", headers=auth_headers
    )
    assert any(
        item["metric_snapshot_id"] == collected.json()["id"]
        for item in reviews.json()["items"]
    )
    strategies = client.get(
        "/v1/projects/prj_subschool/strategy/versions", headers=auth_headers
    )
    assert any(
        item.get("based_on_review_id") and item["status"] == "proposed"
        for item in strategies.json()["items"]
    )

    original_versions = {item["id"]: item["checksum"] for item in body["versions"]}
    revision = client.patch(
        f"/v1/scripts/{body['script_id']}",
        json={
            "hook": "A revised human-approved opening hook.",
            "reason": "Make the first two seconds more concrete for teachers.",
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-script-revision-1"},
    )
    assert revision.status_code == 202
    revised_job = wait_for_job(client, revision.json()["generation_job_id"], auth_headers)
    assert revised_job["status"] == "ready"
    assert revised_job["video_id"] == body["id"]
    revised_video = client.get(f"/v1/videos/{body['id']}", headers=auth_headers).json()
    assert len(revised_video["versions"]) == 4
    for immutable_id, immutable_checksum in original_versions.items():
        old_version = next(item for item in revised_video["versions"] if item["id"] == immutable_id)
        assert old_version["checksum"] == immutable_checksum
    assert revised_video["latest_version_id"] not in original_versions


def test_retry_resumes_from_failed_render_checkpoint(client, auth_headers, monkeypatch) -> None:
    original_renderer = workflow.render_motion_video
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RenderError("synthetic renderer interruption")
        return original_renderer(**kwargs)

    monkeypatch.setattr(workflow, "render_motion_video", fail_once)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Checkpoint-safe rendering",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "approval_mode": "final_only",
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-resume-render-1"},
    )
    assert created.status_code == 202
    job_id = created.json()["generation_job_id"]
    failed = wait_for_job(client, job_id, auth_headers)
    assert failed["status"] == "failed"
    assert failed["current_stage"] == "render"

    retry = client.post(f"/v1/generation-jobs/{job_id}/retry", headers=auth_headers)
    assert retry.status_code == 202
    completed = wait_for_job(client, job_id, auth_headers)
    assert completed["status"] == "ready", completed.get("last_error")
    attempts = {stage["name"]: stage["attempt"] for stage in completed["stages"]}
    assert attempts["research"] == 1
    assert attempts["scene_generation"] == 1
    assert attempts["render"] == 2


def test_interrupted_job_resumes_from_scene_checkpoint_without_duplicate_provider_work(
    client, auth_headers, monkeypatch
) -> None:
    original_write_webvtt = workflow.write_webvtt

    def interrupt_after_scenes(**_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(workflow, "write_webvtt", interrupt_after_scenes)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Durable scene checkpoint",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "approval_mode": "final_only",
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-scene-checkpoint-1"},
    )
    assert created.status_code == 202
    job_id = created.json()["generation_job_id"]

    deadline = time.monotonic() + 20
    interrupted = None
    while time.monotonic() < deadline:
        interrupted = client.get(f"/v1/generation-jobs/{job_id}", headers=auth_headers).json()
        if interrupted.get("interrupted_at") and job_id not in client.app.state.workflow.tasks:
            break
        time.sleep(0.1)
    assert interrupted is not None
    assert interrupted["status"] == "running"
    assert interrupted["current_stage"] == "voice_audio"

    with SessionLocal() as session:
        research_before = session.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.kind == "research_run",
                Resource.project_id == "prj_subschool",
            )
        )
        attempts_before = session.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.kind == "scene_attempt",
                Resource.project_id == "prj_subschool",
            )
        )
        interrupted_resource = session.scalar(
            select(Resource).where(Resource.id == job_id, Resource.kind == "generation_job")
        )
        assert interrupted_resource is not None
        interrupted_resource.status = "failed"
        session.add(interrupted_resource)
        session.commit()

    monkeypatch.setattr(workflow, "write_webvtt", original_write_webvtt)
    retry = client.post(f"/v1/generation-jobs/{job_id}/retry", headers=auth_headers)
    assert retry.status_code == 202
    completed = wait_for_job(client, job_id, auth_headers)
    assert completed["status"] == "ready", completed.get("last_error")

    with SessionLocal() as session:
        research_after = session.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.kind == "research_run",
                Resource.project_id == "prj_subschool",
            )
        )
        attempts_after = session.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.kind == "scene_attempt",
                Resource.project_id == "prj_subschool",
            )
        )
    assert research_after == research_before
    assert attempts_after == attempts_before


def test_unsupported_claim_blocks_before_media_generation(client, auth_headers, monkeypatch) -> None:
    editorial = client.app.state.workflow.editorial
    original = editorial.create_package

    async def unsafe_package(**kwargs):
        package = await original(**kwargs)
        package["policy"] = {
            "decision": "revise",
            "high_risk": True,
            "unsupported_claims": ["Guaranteed student outcomes"],
        }
        return package

    monkeypatch.setattr(editorial, "create_package", unsafe_package)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Unsafe unsupported claim",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-hard-gate-1"},
    )
    blocked = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert blocked["status"] == "blocked"
    fact_gate = next(stage for stage in blocked["stages"] if stage["name"] == "fact_policy")
    media = next(stage for stage in blocked["stages"] if stage["name"] == "scene_generation")
    assert fact_gate["output"]["media_generation_started"] is False
    assert media["status"] == "pending"
