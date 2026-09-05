from __future__ import annotations

import asyncio
import base64
import subprocess
import time
from pathlib import Path
from shutil import which

import pytest
from sqlalchemy import func, select

from apps.api.app import workflow
from apps.api.app.database import SessionLocal
from apps.api.app.models import Resource
from apps.api.app.renderer import RenderError, probe_video, veo_extension_input_compatible


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


def wait_for_job_status(client, job_id: str, headers: dict[str, str], status: str, timeout: float = 35) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/generation-jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] == status:
            return job
        if job["status"] in {"failed", "blocked"}:
            raise AssertionError(job.get("last_error") or job)
        time.sleep(0.15)
    raise AssertionError(f"Job {job_id} did not reach {status} before timeout")


def test_whole_script_review_regenerates_up_to_approval(client, auth_headers, monkeypatch) -> None:
    calls: list[int] = []

    async def review_package(*_args, **_kwargs):
        calls.append(len(calls) + 1)
        approved = len(calls) == 3
        return {
            "approved": approved,
            "score": 91 if approved else 55,
            "valuable": approved,
            "interesting": approved,
            "commercially_effective": approved,
            "logically_coherent": approved,
            "product_accurate": True,
            "issues": [] if approved else [f"Scene {len(calls)} needs a more concrete payoff"],
            "regeneration_feedback": "Replace the generic payoff with one observable audience outcome.",
        }

    monkeypatch.setattr(client.app.state.workflow.editorial, "review_package", review_package)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "A concrete lesson workflow",
            "visual_mode": "storytelling",
            "audio_mode": "veo_native",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "scene_count_min": 2,
            "scene_count_max": 2,
            "scene_count_flex": 0,
            "generation_start_mode": "review_script",
            "test_mode": True,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "whole-script-quality-review-three-attempts"},
    )
    assert created.status_code == 202, created.text
    review = wait_for_job_status(client, created.json()["generation_job_id"], auth_headers, "awaiting_script_review")
    package = next(
        item["output"]["package"]
        for item in review["stages"]
        if item["name"] == "editorial_strategy"
    )
    assert calls == [1, 2, 3]
    assert package["script_quality_review"]["approved"] is True
    assert len(package["script_quality_review"]["attempts"]) == 3


def test_script_review_edit_and_admin_test_mode_skip_veo(client, auth_headers) -> None:
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "A teacher turns one live lesson into reusable practice",
            "visual_mode": "storytelling",
            "audio_mode": "veo_native",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "scene_count_min": 2,
            "scene_count_max": 2,
            "scene_count_flex": 0,
            "generation_start_mode": "review_script",
            "test_mode": True,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-script-review-test-mode-1"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["generation_job_id"]
    review = wait_for_job_status(client, job_id, auth_headers, "awaiting_script_review")
    assert review["current_stage"] == "script_review"
    assert review["test_mode"] is True
    assert review.get("video_id") is None
    original_scene_ids = list(review["scene_ids"])
    rewritten = client.post(
        f"/v1/generation-jobs/{job_id}/script/regenerate",
        json={"feedback": "Make both teachers speak and ground the conflict in repeated lesson preparation."},
        headers=auth_headers,
    )
    assert rewritten.status_code == 202, rewritten.text
    review = wait_for_job_status(client, job_id, auth_headers, "awaiting_script_review")
    assert review["scene_ids"] != original_scene_ids
    package = next(
        item["output"]["package"]
        for item in review["stages"]
        if item["name"] == "editorial_strategy"
    )
    assert package["script_quality_review"]["approved"] is True
    assert package["script_quality_review"]["attempts"][0]["score"] >= 90
    first = package["storyboard"]["scenes"][0]
    scene_id = review["scene_ids"][0]
    edited = client.patch(
        f"/v1/generation-jobs/{job_id}/scenes/{scene_id}",
        json={
            "narration": "I taught this once; why am I rebuilding it tonight?",
            "speaker": first.get("speaker") or "Teacher",
            "speaker_kind": "on_camera",
            "purpose": "Open on a concrete teacher frustration.",
            "story_beat": "Setup and hook",
            "subject": first.get("subject") or "An adult teacher",
            "setting": first.get("setting") or "A lived-in home office after class",
            "action": "The teacher drops a marked-up lesson plan beside a laptop and looks directly at camera.",
            "environment_detail": "Evening light, used notebooks and a cooling mug make the workload tangible.",
            "blocking": "She enters frame, sits, drops the papers and holds eye contact.",
            "camera_direction": "Immediate medium close-up with a restrained push-in.",
            "performance_direction": "Tired but dryly amused, never theatrical.",
            "sound_direction": "Paper lands first; dialogue begins at time zero; no transition sound.",
            "fragment_intent": "Make repeated course-building labor instantly recognizable.",
            "dialogue_intent": "Name the waste in the teacher's own words.",
            "dramatic_conflict": "Her useful live lesson disappears into one-off preparation.",
            "audience_value": "Promise a concrete path from one lesson to reusable practice.",
            "emotional_change": "Resignation turns into curiosity.",
        },
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    refreshed = client.get(f"/v1/generation-jobs/{job_id}", headers=auth_headers).json()
    refreshed_package = next(
        item["output"]["package"]
        for item in refreshed["stages"]
        if item["name"] == "editorial_strategy"
    )
    assert refreshed_package["storyboard"]["scenes"][0]["narration"].startswith("I taught this once")
    started = client.post(f"/v1/generation-jobs/{job_id}/start-scenes", headers=auth_headers)
    assert started.status_code == 202, started.text
    ready = wait_for_job(client, job_id, auth_headers)
    assert ready["status"] == "ready", ready.get("last_error")
    assert ready["actual_cost_usd"] == 0
    video = client.get(f"/v1/videos/{ready['video_id']}", headers=auth_headers).json()
    assert all(
        attempt["model_id"] == "deterministic-test-fixture"
        for scene in video["scenes"]
        for attempt in scene["attempts"]
    )
    assert video["qa_report"]["hard_gate_passed"] is True
    assert video["qa_report"]["visual"]["passed"] is True
    assert all(output["skipped"] is True for output in video["qa_report"]["visual"]["outputs"])
    assert video["qa_report"]["brand"]["evaluated_by"] == "deterministic_test_fixture"
    assert video["qa_report"]["duplicate"] == {
        "passed": True,
        "skipped": True,
        "skip_reason": "Creative duplicate detection is not applicable to a shared Test mode fixture.",
    }
    assert video["score_report"]["blocked_by_hard_gate"] is False


def wait_for_scene_regeneration(client, regeneration_id: str, headers: dict[str, str], timeout: float = 35) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/scene-regenerations/{regeneration_id}", headers=headers)
        assert response.status_code == 200
        regeneration = response.json()
        if regeneration["status"] in {"completed", "failed"}:
            return regeneration
        time.sleep(0.15)
    raise AssertionError(f"Scene regeneration {regeneration_id} did not complete before timeout")


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
            "scene_count_min": 4,
            "scene_count_max": 4,
            "scene_count_flex": 0,
            "continue_scenes": False,
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
    assert {item["format"] for item in body["subtitle_assets"]} == {"srt", "vtt"}
    for subtitle in body["subtitle_assets"]:
        downloaded = client.get(subtitle["url"])
        assert downloaded.status_code == 200
        assert downloaded.content
    assert all(item["captions_burned_in"] is False for item in body["versions"])
    assert all(item["logo_applied"] is False for item in body["versions"])
    assert job["visual_mode"] == "ugc_creator"
    assert job["burn_in_captions"] is False
    assert body["storyboard"]["visual_mode"] == "ugc_creator"
    assert body["storyboard"]["creator_profile"]
    assert len(body["storyboard"]["visual_bible"]) >= 3
    assert len(body["scenes"]) == 4
    assert all("creator-shot UGC" in scene["visual_prompt"] for scene in body["scenes"])
    for scene_index, scene in enumerate(body["scenes"]):
        assert len(scene["attempts"]) == 2
        for attempt in scene["attempts"]:
            assert attempt["last_frame_storage_uri"]
            assert attempt["speech_qa"]["passed"] is True
            assert attempt["speech_qa"]["mode"] == "preflight_timing"
            assert attempt["preview_url"]
            clip = client.get(attempt["preview_url"])
            assert clip.status_code == 200
            assert clip.headers["content-type"] == "video/mp4"
            if scene_index == 0:
                assert attempt["continuity_input_kind"] == "text_only"
            else:
                assert attempt["continuity_input_kind"] == "previous_scene_last_frame"
                previous_attempt = next(
                    item
                    for item in body["scenes"][scene_index - 1]["attempts"]
                    if item["aspect_ratio"] == attempt["aspect_ratio"]
                )
                assert attempt["continuity_input_uri"] == previous_attempt["last_frame_storage_uri"]
    assert body["script"]["script"]["hook"] == "One lesson can do more than you think."
    assert body["qa_report"]["hard_gate_passed"] is True
    assert body["qa_report"]["hard_gates"]["speech_timing"] is True
    assert body["qa_report"]["speech"]["mode"] == "preflight_timing"
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


def test_generation_rejects_an_inverted_scene_range(client, auth_headers) -> None:
    response = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Invalid scene range",
            "scene_count_min": 12,
            "scene_count_max": 4,
            "scene_count_flex": 0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_brand_logo_upload_creates_a_real_render_asset(client, auth_headers) -> None:
    reference_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    uploaded = client.post(
        "/v1/projects/prj_subschool/brand-profile/logo",
        files={"image": ("subschool-logo.png", reference_png, "image/png")},
        data={"rights_confirmed": "true"},
        headers=auth_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert payload["asset"]["type"] == "brand_logo"
    logo = payload["profile"]["visual"]["logo_assets"][0]
    assert logo["asset_id"] == payload["asset"]["id"]
    assert logo["url"]
    media = client.get(logo["url"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"


def test_native_speech_qa_retries_a_clipped_scene_with_shorter_dialogue(
    client, auth_headers, monkeypatch
) -> None:
    reference_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    uploaded = client.post(
        "/v1/projects/prj_subschool/characters/upload",
        files={"image": ("speech-qa-creator.png", reference_png, "image/png")},
        data={
            "name": "Speech QA creator",
            "description": "Adult course creator for automatic speech QA testing",
            "rights_confirmed": "true",
            "adult_confirmed": "true",
        },
        headers=auth_headers,
    )
    assert uploaded.status_code == 201, uploaded.text

    calls = 0

    async def fail_first_clip(*, video_uri, expected_text, duration_target):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "passed": False,
                "transcript": " ".join(expected_text.split()[:-2]),
                "coverage": 0.7,
                "speech_present": True,
                "last_phrase_complete": False,
                "speech_end_seconds": duration_target,
                "issues": ["The final phrase is incomplete or cut off"],
                "provider": "deterministic_test_fixture",
                "demo_data": True,
            }
        return {
            "passed": True,
            "transcript": expected_text,
            "coverage": 1.0,
            "speech_present": True,
            "last_phrase_complete": True,
            "speech_end_seconds": max(0.5, duration_target - 0.5),
            "issues": [],
            "provider": "deterministic_test_fixture",
            "demo_data": True,
        }

    monkeypatch.setattr(client.app.state.workflow.speech_qa, "analyze", fail_first_clip)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Speech QA automatic recovery",
            "visual_mode": "ugc_creator",
            "audio_mode": "veo_native",
            "character_id": uploaded.json()["id"],
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "scene_count_min": 2,
            "scene_count_max": 2,
            "scene_count_flex": 0,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-native-speech-retry-1"},
    )
    assert created.status_code == 202, created.text
    job = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    first_scene = video["scenes"][0]
    latest_attempt = first_scene["attempts"][0]
    assert calls >= 3
    assert first_scene["attempt"] == 2
    assert latest_attempt["automatic_retry"] == 1
    assert latest_attempt["speech_qa"]["passed"] is True
    assert len(first_scene["narration"].split()) <= first_scene["speech_timing"]["word_budget"]
    assert video["qa_report"]["speech"]["mode"] == "transcription"
    assert video["qa_report"]["hard_gates"]["speech_timing"] is True


def test_native_voice_profile_retries_a_changed_speaker_and_reuses_one_seed(
    client, auth_headers, monkeypatch
) -> None:
    comparisons = 0

    async def reject_first_changed_voice(
        *, reference_video_uri, candidate_video_uri, voice_profile
    ):
        nonlocal comparisons
        assert candidate_video_uri
        assert "calm medium-low pitch" in voice_profile
        if not reference_video_uri:
            return {
                "passed": True,
                "same_speaker": True,
                "similarity": 1.0,
                "issues": [],
                "mode": "reference_voice",
                "provider": "deterministic_test_fixture",
                "demo_data": True,
            }
        comparisons += 1
        if comparisons == 1:
            return {
                "passed": False,
                "same_speaker": False,
                "similarity": 0.42,
                "issues": ["Apparent speaker identity changed"],
                "mode": "voice_comparison",
                "provider": "deterministic_test_fixture",
                "demo_data": True,
            }
        return {
            "passed": True,
            "same_speaker": True,
            "similarity": 0.93,
            "issues": [],
            "mode": "voice_comparison",
            "provider": "deterministic_test_fixture",
            "demo_data": True,
        }

    monkeypatch.setattr(
        client.app.state.workflow.speech_qa,
        "compare_voice",
        reject_first_changed_voice,
    )
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Native voice identity lock",
            "visual_mode": "ugc_creator",
            "audio_mode": "veo_native",
            "native_voice_preset": "calm_expert",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "scene_count_min": 2,
            "scene_count_max": 2,
            "scene_count_flex": 0,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-native-voice-retry-1"},
    )
    assert created.status_code == 202, created.text
    job = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    assert job["native_voice_preset"] == "calm_expert"
    assert isinstance(job["veo_seed"], int)
    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    first_attempt = video["scenes"][0]["attempts"][0]
    second_scene = video["scenes"][1]
    second_attempt = second_scene["attempts"][0]
    assert comparisons == 2
    assert second_scene["attempt"] == 2
    assert second_attempt["automatic_retry"] == 1
    assert second_attempt["voice_qa"]["passed"] is True
    assert second_attempt["voice_qa"]["similarity"] == 0.93
    assert first_attempt["veo_seed"] == second_attempt["veo_seed"] == job["veo_seed"]
    assert "No fade, dissolve" in second_scene["visual_prompt"]
    assert video["qa_report"]["hard_gates"]["voice_identity"] is True
    assert video["qa_report"]["voice_identity"]["preset"] == "calm_expert"


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


def test_failed_editorial_stage_retries_from_its_checkpoint_without_research(
    client, auth_headers, monkeypatch
) -> None:
    manager = client.app.state.workflow
    original_search = manager.parallel.search
    original_create_package = manager.editorial.create_package
    research_calls = 0
    editorial_calls = 0

    async def counted_search(*args, **kwargs):
        nonlocal research_calls
        research_calls += 1
        return await original_search(*args, **kwargs)

    async def fail_editorial_once(*args, **kwargs):
        nonlocal editorial_calls
        editorial_calls += 1
        if editorial_calls == 1:
            raise RuntimeError(
                "400 INVALID_ARGUMENT: The specified schema produces a constraint "
                "that has too many states for serving"
            )
        return await original_create_package(*args, **kwargs)

    monkeypatch.setattr(manager.parallel, "search", counted_search)
    monkeypatch.setattr(manager.editorial, "create_package", fail_editorial_once)
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Resume after editorial schema failure",
            "visual_mode": "storytelling",
            "audio_mode": "veo_native",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "scene_count_min": 2,
            "scene_count_max": 2,
            "scene_count_flex": 0,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-editorial-stage-retry-1"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["generation_job_id"]
    failed = wait_for_job(client, job_id, auth_headers)
    assert failed["status"] == "failed"
    assert failed["current_stage"] == "editorial_strategy"
    assert research_calls == 1
    assert next(stage for stage in failed["stages"] if stage["name"] == "research")["status"] == "completed"

    retried = client.post(
        f"/v1/generation-jobs/{job_id}/stages/editorial_strategy/retry",
        headers=auth_headers,
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["resume_from_stage"] == "editorial_strategy"
    assert retried.json()["preserved_stages"] == ["intake", "research"]

    completed = wait_for_job(client, job_id, auth_headers)
    assert completed["status"] == "ready", completed.get("last_error")
    attempts = {stage["name"]: stage["attempt"] for stage in completed["stages"]}
    assert attempts["intake"] == 1
    assert attempts["research"] == 1
    assert attempts["editorial_strategy"] == 2
    assert research_calls == 1
    assert editorial_calls == 2
    assert completed["visual_mode"] == "storytelling"
    assert completed["audio_mode"] == "veo_native"


def test_selective_scene_regeneration_executes_and_appends_video_version(client, auth_headers) -> None:
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Selective UGC scene regeneration",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 8,
            "approval_mode": "final_only",
            "visual_mode": "ugc_creator",
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-scene-regeneration-1"},
    )
    assert created.status_code == 202
    job = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready"
    original = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    assert len(original["versions"]) == 1
    scene = original["scenes"][0]
    assert scene["locked"] is False

    queued = client.post(
        f"/v1/scenes/{scene['id']}/regenerate",
        json={
            "reason": "Use a more authentic handheld creator action.",
            "visual_prompt": (
                "Authentic handheld creator-shot UGC b-roll in a daylight home office. "
                "The recurring creator opens a notebook; no visible speaking, readable text or logos."
            ),
        },
        headers=auth_headers,
    )
    assert queued.status_code == 202
    regeneration = wait_for_scene_regeneration(client, queued.json()["regeneration_id"], auth_headers)
    assert regeneration["status"] == "completed", regeneration.get("error")
    assert regeneration["attempt_ids"]

    refreshed_job = client.get(f"/v1/generation-jobs/{job['id']}", headers=auth_headers).json()
    refreshed_video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    assert refreshed_job["status"] == "ready"
    assert len(refreshed_video["versions"]) == 2
    assert refreshed_video["latest_version_id"] != original["latest_version_id"]
    refreshed_scene = next(item for item in refreshed_video["scenes"] if item["id"] == scene["id"])
    assert refreshed_scene["attempt"] == 2
    assert "authentic handheld" in refreshed_scene["visual_prompt"].lower()


def test_native_ugc_regeneration_cascades_through_following_extensions(client, auth_headers) -> None:
    created = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Continuous native UGC regeneration",
            "aspect_ratios": ["9:16"],
            "target_duration_seconds": 15,
            "visual_mode": "ugc_creator",
            "audio_mode": "veo_native",
            "scene_count_min": 2,
            "scene_count_max": 3,
            "scene_count_flex": 0,
            "max_cost_usd": 10,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-native-ugc-cascade-1"},
    )
    assert created.status_code == 202, created.text
    job = wait_for_job(client, created.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    scenes = sorted(video["scenes"], key=lambda item: item["position"])
    assert len(scenes) == 2

    queued = client.post(
        f"/v1/scenes/{scenes[0]['id']}/regenerate",
        json={"reason": "Strengthen the opening action and rebuild the dependent extension."},
        headers=auth_headers,
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["cascade_scene_count"] == 2
    regeneration = wait_for_scene_regeneration(client, queued.json()["regeneration_id"], auth_headers)
    assert regeneration["status"] == "completed", regeneration.get("error")
    assert len(regeneration["attempt_ids"]) == 2

    refreshed = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    refreshed_scenes = sorted(refreshed["scenes"], key=lambda item: item["position"])
    assert [item["attempt"] for item in refreshed_scenes] == [2, 2]


def test_continuous_native_ugc_uses_a_rolling_window_beyond_36_seconds(client, auth_headers) -> None:
    response = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Native UGC too long",
            "target_duration_seconds": 40,
            "visual_mode": "ugc_creator",
            "audio_mode": "veo_native",
        },
        headers=auth_headers,
    )

    assert response.status_code == 202, response.text
    job = wait_for_job(client, response.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    scenes = sorted(video["scenes"], key=lambda item: item["position"])
    assert len(scenes) == 6
    assert all(scene["continuation_track"] == "creator" for scene in scenes)
    assert scenes[-1]["attempts"][0]["continuity_input_kind"] == "continuation_track:creator"


def test_storytelling_continuation_uses_the_previous_scene_for_each_role(client, auth_headers) -> None:
    response = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={
            "title": "Two colleagues stop rebuilding one course",
            "target_duration_seconds": 30,
            "scene_count_min": 5,
            "scene_count_max": 6,
            "scene_count_flex": 0,
            "visual_mode": "storytelling",
            "audio_mode": "veo_native",
            "continue_scenes": True,
            "max_cost_usd": 20,
        },
        headers={**auth_headers, "Idempotency-Key": "pipeline-story-role-tracks-1"},
    )

    assert response.status_code == 202, response.text
    job = wait_for_job(client, response.json()["generation_job_id"], auth_headers)
    assert job["status"] == "ready", job.get("last_error")
    video = client.get(f"/v1/videos/{job['video_id']}", headers=auth_headers).json()
    scenes = sorted(video["scenes"], key=lambda item: item["position"])
    maya_one, leo_one, maya_two, leo_two = scenes[:4]
    assert [item["continuation_track"] for item in scenes[:4]] == ["maya", "leo", "maya", "leo"]
    assert maya_one["attempts"][0]["continuity_input_kind"] == "continuation_track_root:maya"
    assert leo_one["attempts"][0]["continuity_input_kind"] == "continuation_track_root:leo"
    assert maya_two["attempts"][0]["continuity_input_uri"] == maya_one["attempts"][0]["continuation_storage_uri"]
    assert leo_two["attempts"][0]["continuity_input_uri"] == leo_one["attempts"][0]["continuation_storage_uri"]

    queued = client.post(
        f"/v1/scenes/{maya_one['id']}/regenerate",
        json={"reason": "Change Maya's opening while preserving Leo's branch."},
        headers=auth_headers,
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["cascade_scene_count"] == len([item for item in scenes if item["continuation_track"] == "maya"])
    regeneration = wait_for_scene_regeneration(client, queued.json()["regeneration_id"], auth_headers)
    assert regeneration["status"] == "completed", regeneration.get("error")


@pytest.mark.parametrize("legacy_fault", ["offset", "corrupt"])
def test_retry_repairs_legacy_conditioning_without_regenerating_accepted_scenes(
    client, auth_headers, monkeypatch, legacy_fault,
) -> None:
    original_render = workflow.render_scene_fixture
    calls: dict[str, int] = {}

    def fail_third_scene_once(**kwargs):
        label = kwargs["label"]
        calls[label] = calls.get(label, 0) + 1
        if label == "Scene 3" and calls[label] == 1:
            raise RuntimeError("Injected provider interruption")
        return original_render(**kwargs)

    monkeypatch.setattr(workflow, "render_scene_fixture", fail_third_scene_once)
    response = client.post(
        "/v1/projects/prj_subschool/generation-jobs",
        json={"title": f"Legacy conditioning recovery {legacy_fault}", "target_duration_seconds": 20,
              "visual_mode": "ugc_creator", "audio_mode": "veo_native", "continue_scenes": True,
              "scene_count_min": 3, "scene_count_max": 3, "scene_count_flex": 0, "max_cost_usd": 20},
        headers=auth_headers,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["generation_job_id"]
    failed = wait_for_job(client, job_id, auth_headers)
    assert failed["status"] == "failed"
    with SessionLocal() as session:
        attempts = session.scalars(select(Resource).where(
            Resource.kind == "scene_attempt", Resource.data["generation_job_id"].as_string() == job_id,
        ).order_by(Resource.created_at)).all()
        assert len(attempts) == 2
        accepted_ids = [a.id for a in attempts]
        conditioning = Path(attempts[-1].data["continuation_conditioning_uri"])
        if legacy_fault == "offset":
            shifted = conditioning.with_name("shifted_test.mp4")
            ffmpeg = which("ffmpeg")
            assert ffmpeg
            subprocess.run([
                ffmpeg, "-v", "error", "-y", "-i", str(conditioning),
                "-vf", "setpts=PTS+1/(24*TB)", "-fps_mode", "passthrough",
                "-c:v", "libx264", "-c:a", "copy", str(shifted),
            ], check=True, capture_output=True)
            conditioning.write_bytes(shifted.read_bytes())
            assert not veo_extension_input_compatible(probe_video(conditioning))
        else:
            conditioning.write_bytes(b"corrupt legacy context")

    retry = client.post(f"/v1/generation-jobs/{job_id}/retry", headers=auth_headers)
    assert retry.status_code == 202, retry.text
    ready = wait_for_job(client, job_id, auth_headers)
    assert ready["status"] == "ready", ready.get("last_error")
    assert calls == {"Scene 1": 1, "Scene 2": 1, "Scene 3": 2}
    with SessionLocal() as session:
        attempts = session.scalars(select(Resource).where(
            Resource.kind == "scene_attempt", Resource.data["generation_job_id"].as_string() == job_id,
        ).order_by(Resource.created_at)).all()
        assert [a.id for a in attempts[:2]] == accepted_ids
        assert len(attempts) == 3
        repaired = attempts[1]
        assert repaired.data["continuation_contract_version"] == 2
        assert attempts[2].data["continuity_input_uri"] == repaired.data["continuation_storage_uri"]
        assert veo_extension_input_compatible(probe_video(Path(repaired.data["continuation_conditioning_uri"])))


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
