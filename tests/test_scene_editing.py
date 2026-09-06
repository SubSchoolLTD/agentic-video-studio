from __future__ import annotations

import pytest
from sqlalchemy import select

from apps.api.app.database import SessionLocal
from apps.api.app.idea_lifecycle import idea_status
from apps.api.app.models import Resource, Wallet
from apps.api.app.repository import ResourceRepository
from apps.api.app.workflow import initial_stage_state


@pytest.fixture
def production(client):
    with SessionLocal() as session:
        repo = ResourceRepository(session)

        def add(kind, data, status="ready"):
            return repo.add(
                kind=kind, organization_id="org_demo", project_id="prj_subschool", status=status, data=data
            )

        job = add(
            "generation_job",
            {
                "current_stage": "completed",
                "audio_mode": "veo_native",
                "continue_scenes": True,
                "aspect_ratios": ["9:16", "16:9"],
                "stages": initial_stage_state(),
                "test_mode": True,
            },
        )
        story = add("storyboard", {"generation_job_id": job.id, "scenes": []})
        script = add("script", {"script": {"beats": []}})
        video = add("video", {"latest_version_id": "old-render", "generation_job_id": job.id})
        idea = add("idea", {"generation_job_id": job.id})
        scenes = [
            add(
                "scene",
                {
                    "id": f"scene_{i}",
                    "position": i,
                    "storyboard_id": story.id,
                    "character_key": "creator",
                    "continuation_track": "creator",
                    "duration_target": 6 if i == 1 else 7,
                    "narration": "One useful thought.",
                    "speaker_kind": "on_camera",
                    "locked": True,
                    "visual_prompt_base": "Creator walks from home to the library.",
                    "visual_prompt": "Old compiled prompt.",
                },
                "generated",
            )
            for i in range(1, 4)
        ]
        repo.update(story, data={"scenes": [scene.data for scene in scenes]})
        stages = initial_stage_state()
        for stage in stages:
            stage["status"] = "completed"
            if stage["name"] == "storyboard":
                stage["output"] = {"storyboard_id": story.id}
            if stage["name"] == "script":
                stage["output"] = {"script_id": script.id}
            if stage["name"] == "editorial_strategy":
                stage["output"] = {"package": {"storyboard": {"scenes": [scene.data for scene in scenes]}}}
        repo.update(job, data={"video_id": video.id, "stages": stages})
        return {
            "job": job.id,
            "story": story.id,
            "script": script.id,
            "video": video.id,
            "idea": idea.id,
            "scenes": [scene.id for scene in scenes],
        }


def test_prompt_edits_all_checkpoints_but_not_approved_video(client, auth_headers, production):
    scene_id = production["scenes"][1]
    body = {
        "narration": "I test my recall outside.",
        "visual_prompt": "Creator walks across a quiet courtyard and closes a notebook.",
        "speaker_kind": "on_camera",
    }
    rewrite = client.post(
        f"/v1/scenes/{scene_id}/rewrite-prompt",
        headers=auth_headers,
        json={**body, "feedback": "Keep the dialogue, add movement."},
    )
    assert rewrite.status_code == 200, rewrite.text
    with SessionLocal() as session:
        assert session.get(Resource, scene_id).data["narration"] == "One useful thought."
    saved = client.patch(f"/v1/scenes/{scene_id}/prompt", headers=auth_headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["visual_prompt_base"] == body["visual_prompt"]
    assert saved.json()["visual_prompt"].count(body["narration"]) == 1
    with SessionLocal() as session:
        assert session.get(Resource, production["video"]).data["latest_version_id"] == "old-render"
        assert session.get(Resource, scene_id).data["locked"] is True
        assert session.get(Resource, scene_id).status == "generated"
        assert session.get(Resource, production["story"]).data["scenes"][1]["narration"] == body["narration"]
        assert (
            session.get(Resource, production["script"]).data["script"]["beats"] == []
        )  # minimal fixture has no beats
        job = session.get(Resource, production["job"])
        assert (
            next(s for s in job.data["stages"] if s["name"] == "editorial_strategy")["output"]["package"][
                "storyboard"
            ]["scenes"][1]["narration"]
            == body["narration"]
        )


def test_quote_confirmation_test_mode_and_duplicate_guard(client, auth_headers, production, monkeypatch):
    scheduled = []
    monkeypatch.setattr(client.app.state.workflow, "schedule_scene_regeneration", scheduled.append)
    url = f"/v1/scenes/{production['scenes'][0]}/regenerate"
    body = {"reason": "Improve the physical action"}
    quote = client.post(url + "/quote", headers=auth_headers, json=body).json()
    assert quote["scene_positions"] == [1, 2, 3]
    assert quote["quantity"] == (6 + 7 + 7) * 2
    assert quote["charge_cents"] == 0
    assert quote["unlock_required"] is True
    assert scheduled == []
    assert client.post(url, headers=auth_headers, json=body).status_code == 409
    confirmed = {**body, "unlock_approved": True, "quote_fingerprint": quote["fingerprint"]}
    queued = client.post(url, headers=auth_headers, json=confirmed)
    assert queued.status_code == 202, queued.text
    assert len(scheduled) == 1
    job = client.get(f"/v1/generation-jobs/{production['job']}", headers=auth_headers).json()
    assert job["status"] == "queued"
    assert job["current_stage"] == "scene_generation"
    assert next(s for s in job["stages"] if s["name"] == "render")["status"] == "pending"
    assert client.post(url, headers=auth_headers, json=confirmed).status_code == 409
    # A selective take has its own task and charge. The original production's
    # cancellation endpoint must not refund it while the take keeps running.
    assert client.post(
        f"/v1/generation-jobs/{production['job']}/cancel", headers=auth_headers,
    ).status_code == 409
    assert (
        client.patch(
            f"/v1/scenes/{production['scenes'][0]}/prompt",
            headers=auth_headers,
            json={"narration": "New text.", "visual_prompt": "A new location."},
        ).status_code
        == 409
    )
    with SessionLocal() as session:
        assert idea_status(session, session.get(Resource, production["idea"])) == "video_generation"
        # Do not leave a queued fake job for restart recovery in other tests.
        repo = ResourceRepository(session)
        repo.update(session.get(Resource, scheduled[0]), status="cancelled")
        repo.update(
            session.get(Resource, production["job"]), status="ready", data={"active_regeneration_id": None}
        )


def test_quote_changed_prompt_and_insufficient_balance(client, auth_headers, production, monkeypatch):
    monkeypatch.setattr(
        client.app.state.workflow,
        "schedule_scene_regeneration",
        lambda _: pytest.fail("Must not start generation"),
    )
    with SessionLocal() as session:
        ResourceRepository(session).update(
            session.get(Resource, production["job"]), data={"test_mode": False}
        )
    scene_id = production["scenes"][1]
    url = f"/v1/scenes/{scene_id}/regenerate"
    body = {"reason": "Improve this scene"}
    quote = client.post(url + "/quote", headers=auth_headers, json=body).json()
    assert quote["quantity"] == 14
    assert quote["charge_cents"] > 0
    client.patch(
        f"/v1/scenes/{scene_id}/prompt",
        headers=auth_headers,
        json={"narration": "New complete thought.", "visual_prompt": "A person walks through a park."},
    )
    assert (
        client.post(
            url,
            headers=auth_headers,
            json={**body, "quote_fingerprint": quote["fingerprint"], "unlock_approved": True},
        ).status_code
        == 409
    )
    with SessionLocal() as session:
        wallet = session.get(Wallet, "org_demo")
        previous_balance = wallet.balance_cents
        wallet.balance_cents = 0
        session.commit()
    try:
        result = client.post(url, headers=auth_headers, json={**body, "unlock_approved": True})
        assert result.status_code == 402, result.text
        with SessionLocal() as session:
            assert session.get(Resource, production["job"]).status == "ready"
            assert session.get(Resource, scene_id).data["locked"] is True
    finally:
        with SessionLocal() as session:
            session.get(Wallet, "org_demo").balance_cents = previous_balance
            session.commit()


def test_idea_lifecycle_follows_latest_job_and_actual_publication(client, production):
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        idea = session.get(Resource, production["idea"])
        job = session.get(Resource, production["job"])
        assert idea.status == "video_ready"
        publication = repo.add(
            kind="publication",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="export_ready",
            data={"video_version_id": "old-render"},
        )
        assert idea.status == "video_ready"
        repo.update(publication, status="published")
        assert idea.status == "published"
        repo.update(job, status="running", data={"current_stage": "scene_generation"})
        assert idea.status == "video_generation"
        repo.update(job, status="failed")
        assert idea.status == "video_generation"
        repo.update(job, status="awaiting_script_review", data={"current_stage": "script_review"})
        assert idea.status == "script_generation"
        repo.update(job, status="cancelled")
        repo.update(idea, data={"generation_job_id": None}, status="planned")
        assert idea.status == "selected"
        foreign = repo.add(
            kind="generation_job",
            organization_id="different-org",
            project_id="different-project",
            status="ready",
            data={"video_id": production["video"]},
        )
        repo.update(idea, data={"generation_job_id": foreign.id})
        assert idea.status == "selected"
        assert session.scalar(select(Resource.id).where(Resource.id == idea.id)) == idea.id
