from __future__ import annotations

import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from apps.api.app.database import SessionLocal
from apps.api.app.models import CreditLedger, Resource
from apps.api.app.repository import ResourceRepository


def wait_job(client, job_id, headers):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job = client.get(f"/v1/generation-jobs/{job_id}", headers=headers).json()
        if job["status"] in {"ready", "failed"}:
            return job
        time.sleep(0.1)
    pytest.fail("Timed out waiting for fixture production")


@pytest.fixture
def rendered(client, auth_headers):
    response = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        headers=auth_headers,
        json={
            "title": "Keep the strongest version of each scene",
            "target_duration_seconds": 8,
            "visual_mode": "ugc_creator",
            "audio_mode": "veo_native",
            "test_mode": True,
            "aspect_ratios": ["9:16"],
            "max_cost_usd": 10,
        },
    )
    assert response.status_code == 202, response.text
    job = wait_job(client, response.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    return job, client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()


def test_take_history_and_reassembly_preserve_media_and_charges(client, auth_headers, rendered, monkeypatch):
    job, original = rendered
    scene = original["scenes"][0]
    old_take = scene["attempt_history"][0]
    old_line = old_take["narration"]
    assert original["versions"][0]["scene_attempt_ids"][scene["id"]] == old_take["id"]
    with SessionLocal() as session:
        caption_asset = session.get(Resource, original["versions"][0]["caption_asset_id"])
        original_caption_path = Path(caption_asset.data["storage_uri"])
        original_caption_bytes = original_caption_path.read_bytes()
    assert (
        client.patch(
            f"/v1/scenes/{scene['id']}/prompt",
            headers=auth_headers,
            json={
                "narration": "A different, complete line.",
                "visual_prompt": "Creator walks through the courtyard with one closed notebook.",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/scenes/{scene['id']}/regenerate",
            headers=auth_headers,
            json={
                "reason": "Test the replacement take",
                "unlock_approved": True,
            },
        ).status_code
        == 202
    )
    job = wait_job(client, job["id"], auth_headers)
    assert job["status"] == "ready"
    current = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    assert len(current["scenes"][0]["attempt_history"]) == 2
    assert current["scenes"][0]["attempt_history"][0]["attempt"] == 2
    with SessionLocal() as session:
        scene_before = dict(session.get(Resource, scene["id"]).data)
        attempt_count = session.scalar(
            select(func.count()).select_from(Resource).where(Resource.kind == "scene_attempt")
        )
        ledger_count = session.scalar(select(func.count()).select_from(CreditLedger))
        old_files = {}
        for version in current["versions"]:
            stored = session.get(Resource, version["id"])
            asset = session.get(Resource, stored.data["render_asset_id"])
            path = Path(asset.data["storage_uri"])
            old_files[path] = path.read_bytes()
    body = {
        "base_version_id": current["latest_version_id"],
        "aspect_ratio": "9:16",
        "selections": [
            {
                "scene_id": item["id"],
                "attempt_id": old_take["id"]
                if item["id"] == scene["id"]
                else item["attempt_history"][0]["id"],
            }
            for item in current["scenes"]
        ],
    }
    endpoint = f"/v1/videos/{job['video_id']}/reassemble"
    assert (
        client.post(
            endpoint, headers=auth_headers, json={**body, "base_version_id": original["latest_version_id"]}
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint, headers=auth_headers, json={**body, "selections": body["selections"] * 2}
        ).status_code
        == 422
    )
    assert (
        client.post(endpoint, headers=auth_headers, json={**body, "aspect_ratio": "16:9"}).status_code == 422
    )
    with SessionLocal() as session:
        foreign = ResourceRepository(session).add(
            kind="scene_attempt",
            organization_id="foreign",
            project_id="private",
            status="passed",
            data=old_take,
        )
        foreign_id = foreign.id
    invalid = [{**body["selections"][0], "attempt_id": foreign_id}, *body["selections"][1:]]
    assert (
        client.post(endpoint, headers=auth_headers, json={**body, "selections": invalid}).status_code == 404
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("Reassembly must not generate scenes, synthesize native audio, or publish")

    monkeypatch.setattr(client.app.state.workflow, "_generate_scene_with_qa", forbidden)
    monkeypatch.setattr(client.app.state.workflow.tts, "synthesize", forbidden)
    monkeypatch.setattr(client.app.state.workflow, "_complete_automatic_publications", forbidden)
    monkeypatch.setattr(
        "apps.api.app.workflow.settle_feature_charge",
        lambda *args, **kwargs: pytest.fail("Do not settle old charges again"),
    )
    queued = client.post(endpoint, headers=auth_headers, json=body)
    assert queued.status_code == 202, queued.text
    assert client.post(endpoint, headers=auth_headers, json=body).status_code == 409
    finished = wait_job(client, job["id"], auth_headers)
    assert finished["status"] == "ready", finished.get("last_error")
    assert finished["actual_cost_usd"] == job["actual_cost_usd"]
    final = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    assert len(final["versions"]) == 3
    version = next(item for item in final["versions"] if item["id"] == final["latest_version_id"])
    assert version["scene_attempt_ids"][scene["id"]] == old_take["id"]
    assert version["scene_snapshots"][0]["narration"] == old_line
    assert len(version["subtitle_assets"]) == 2
    assert len({item["subtitle_assets"][0]["url"].split("?")[0] for item in final["versions"]}) == 3
    assert final["status"] == "approval_required"
    with SessionLocal() as session:
        assert session.get(Resource, scene["id"]).data == scene_before
        assert (
            session.scalar(select(func.count()).select_from(Resource).where(Resource.kind == "scene_attempt"))
            == attempt_count + 1
        )  # foreign validation fixture
        assert session.scalar(select(func.count()).select_from(CreditLedger)) == ledger_count
        captions = session.get(Resource, version["caption_asset_id"])
        assert old_line in Path(captions.data["storage_uri"]).read_text()
        operation = session.get(Resource, queued.json()["reassembly_id"])
        assert operation.status == "completed"
    assert all(path.read_bytes() == content for path, content in old_files.items())
    assert original_caption_path.read_bytes() == original_caption_bytes


def test_failed_reassembly_keeps_the_previous_render(client, auth_headers, rendered, monkeypatch):
    job, video = rendered

    async def fail_render(**kwargs):
        raise RuntimeError("Fixture renderer interrupted")

    monkeypatch.setattr(client.app.state.workflow, "_complete_from_render", fail_render)
    response = client.post(
        f"/v1/videos/{video['id']}/reassemble",
        headers=auth_headers,
        json={
            "base_version_id": video["latest_version_id"],
            "aspect_ratio": "9:16",
            "selections": [
                {"scene_id": scene["id"], "attempt_id": scene["attempt_history"][0]["id"]}
                for scene in video["scenes"]
            ],
        },
    )
    assert response.status_code == 202
    failed = wait_job(client, job["id"], auth_headers)
    assert failed["status"] == "failed"
    assert failed["last_reassembly_error"] == "Fixture renderer interrupted"
    assert not failed["active_reassembly_id"]
    assert client.post(f"/v1/generation-jobs/{job['id']}/retry", headers=auth_headers).status_code == 409
    after = client.get(f"/v1/videos/{video['id']}", headers=auth_headers).json()
    assert after["latest_version_id"] == video["latest_version_id"]
    assert len(after["versions"]) == 1
