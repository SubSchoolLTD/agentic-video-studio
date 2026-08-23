from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from apps.api.app.providers import (
    EditorialPackage,
    EditorialProvider,
    ResearchPacket,
    TopicCandidateProvider,
    _rebalance_candidate_mix,
    _strip_prompt_tokens,
    apply_narration_to_scene,
    continuous_ugc_scene_layout,
    vertex_text_locations,
)
from apps.api.app.repository import ResourceRepository
from apps.api.app.workflow import (
    editorial_deployment_repair_field,
    generation_deployment_repair_field,
    generation_retry_delay_seconds,
    retryable_generation_error,
)


def editorial_payload() -> dict:
    scenes = []
    for index in range(2):
        scenes.append(
            {
                "id": f"scene_{index + 1}",
                "position": index + 1,
                "start_sec": index * 4,
                "end_sec": (index + 1) * 4,
                "duration_target": 4,
                "purpose": "hook" if index == 0 else "proof",
                "narration": "A short spoken line.",
                "on_screen_text": None,
                "visual_prompt": "A creator speaks directly to camera.",
                "continuity_notes": "Same creator and room.",
                "shot_type": "medium close-up",
                "subject": "course creator",
                "setting": "home studio",
                "action": "speaks naturally",
                "camera_direction": "locked handheld framing",
                "performance_direction": "warm and conversational",
            }
        )
    return {
        "production_brief": {
            "objective": "awareness",
            "audience": "course creators",
            "format": "short-form UGC",
            "duration_target": 8,
            "mandatory_points": "Explain the value of reusable learning experiences.",
            "forbidden_claims": [],
            "budget_class": "standard",
            "visual_mode": "ugc_creator",
            "aspect_ratios": ["9:16"],
        },
        "concepts": [
            {"title": "One", "hook": "Start here", "angle": "Value", "score": 90},
        ],
        "script": {
            "title": "Reusable expertise",
            "hook": "Start here",
            "voiceover": ["A short spoken line.", "A second concise beat."],
            "duration_target": 8,
            "cta": "Create your first course.",
            "caption_candidates": [],
            "hashtags": [],
        },
        "policy": {"decision": "pass", "high_risk": False, "unsupported_claims": []},
        "storyboard": {
            "scenes": scenes,
            "visual_mode": "ugc_creator",
            "creator_profile": {
                "name": "Alex",
                "age_range": "30-40",
                "delivery": "warm and conversational",
            },
            "visual_bible": ["same creator", "same room", "warm daylight"],
        },
    }


def test_editorial_package_normalizes_lossless_gemini_shape_variations() -> None:
    package = EditorialPackage.model_validate_json(json.dumps(editorial_payload())).model_dump()

    assert package["production_brief"]["mandatory_points"] == [
        "Explain the value of reusable learning experiences."
    ]
    assert package["script"]["voiceover"] == "A short spoken line. A second concise beat."
    assert package["storyboard"]["creator_profile"] == (
        "name: Alex; age range: 30-40; delivery: warm and conversational"
    )
    assert [scene["on_screen_text"] for scene in package["storyboard"]["scenes"]] == ["", ""]


def test_editorial_package_defaults_budget_class_when_gemini_omits_it() -> None:
    payload = editorial_payload()
    payload["production_brief"].pop("budget_class")

    package = EditorialPackage.model_validate(payload).model_dump()

    assert package["production_brief"]["budget_class"] == "standard"


def test_editorial_package_normalizes_missing_visual_bible_and_speaker_aliases() -> None:
    payload = editorial_payload()
    payload["storyboard"].pop("visual_bible")
    payload["storyboard"]["character_map"] = [
        {
            "key": "maya",
            "name": "Maya",
            "role": "teacher",
            "speaker_kind": "on-screen_actor",
        },
        {
            "key": "narrator",
            "name": "Narrator",
            "role": "voice over",
            "speaker_kind": "off-screen",
        },
    ]
    payload["storyboard"]["scenes"][0]["speaker_kind"] = "on-screen_actor"

    package = EditorialPackage.model_validate(payload).model_dump()

    assert len(package["storyboard"]["visual_bible"]) == 3
    assert package["storyboard"]["scenes"][0]["speaker_kind"] == "on_camera"
    assert [item["speaker_kind"] for item in package["storyboard"]["character_map"]] == [
        "on_camera",
        "voice_over",
    ]


@pytest.mark.asyncio
async def test_dialogue_fit_uses_local_fallback_when_vertex_is_throttled(monkeypatch) -> None:
    provider = EditorialProvider(Settings(provider_mode="live"))

    def throttled(*_args, **_kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(provider, "_fit_dialogue_with_gemini", throttled)
    scenes = [
        {
            "id": "scene_1",
            "duration_target": 4,
            "purpose": "hook",
            "narration": "This deliberately long spoken sentence must be shortened before the generated scene ends abruptly.",
            "visual_prompt_base": "A creator speaks to camera.",
            "visual_mode": "ugc_creator",
        }
    ]

    fitted = await provider.fit_dialogue(scenes, native_audio=True)

    assert fitted[0]["speech_timing"]["adjusted_before_generation"] is True
    assert fitted[0]["speech_timing"]["word_count"] <= fitted[0]["speech_timing"]["word_budget"]


def test_storytelling_native_audio_locks_the_named_role_without_a_global_narrator() -> None:
    scene = apply_narration_to_scene(
        {
            "visual_mode": "storytelling",
            "speaker": "Maya",
            "visual_prompt_base": "Locked cast bible: Maya and Leo keep their identity.",
        },
        "I taught this lesson twice already.",
        native_audio=True,
        voice_profile="a grounded conversational cast",
    )

    assert 'Maya says exactly' in scene["visual_prompt"]
    assert "Preserve Maya's distinct" in scene["visual_prompt"]
    assert "Do not swap voices between roles" in scene["visual_prompt"]
    assert "add a narrator" in scene["visual_prompt"]


def test_invalid_editorial_payload_failure_is_recovered_once_after_deployment() -> None:
    job_data = {
        "current_stage": "editorial_strategy",
        "last_error": {
            "message": "Editorial provider returned invalid JSON twice: mandatory_points Input should be a valid array"
        },
    }

    repair_field = editorial_deployment_repair_field(job_data)

    assert repair_field == "editorial_payload_normalization_v2_retry_at"
    job_data["editorial_payload_normalization_retry_at"] = "2026-08-23T00:00:00+00:00"
    assert editorial_deployment_repair_field(job_data) == repair_field
    job_data[repair_field] = "2026-08-23T00:00:00+00:00"
    assert editorial_deployment_repair_field(job_data) is None


def test_generation_job_can_only_be_claimed_once_across_workers(client) -> None:
    with SessionLocal() as session:
        job = ResourceRepository(session).add(
            resource_id="gener_atomic_claim_contract",
            kind="generation_job",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="queued",
            data={"current_stage": "intake", "stages": []},
        )

    manager = client.app.state.workflow
    assert manager._claim_generation_job(job.id) is True
    assert manager._claim_generation_job(job.id) is False


def test_legacy_empty_veo_response_is_recovered_from_scene_checkpoint_once() -> None:
    job_data = {
        "current_stage": "scene_generation",
        "last_error": {"message": "'NoneType' object is not subscriptable"},
    }

    repair_field = generation_deployment_repair_field(job_data)

    assert repair_field == "veo_empty_response_v1_retry_at"
    job_data[repair_field] = "2026-08-23T02:07:12+00:00"
    assert generation_deployment_repair_field(job_data) is None


def test_veo_high_load_is_retryable_and_recovered_from_scene_checkpoint_once() -> None:
    message = (
        "Veo operation failed: {'code': 8, 'message': 'The service is currently experiencing high load "
        "and cannot process your request. Please try again later.'}"
    )
    job_data = {"current_stage": "scene_generation", "last_error": {"message": message}}

    assert retryable_generation_error(RuntimeError(message)) is True
    repair_field = generation_deployment_repair_field(job_data)

    assert repair_field == "veo_high_load_v1_retry_at"
    job_data[repair_field] = "2026-08-23T02:26:33+00:00"
    assert generation_deployment_repair_field(job_data) is None


def test_invalid_editorial_json_is_automatically_retryable() -> None:
    assert retryable_generation_error(
        RuntimeError("Editorial provider returned invalid JSON twice: budget_class Field required")
    ) is True


def test_vertex_quota_retry_uses_long_exponential_backoff() -> None:
    error = RuntimeError("429 RESOURCE_EXHAUSTED long_running_online_prediction_requests_per_base_model")

    assert [generation_retry_delay_seconds(error, attempt) for attempt in range(5)] == [30, 60, 120, 240, 240]
    assert generation_retry_delay_seconds(RuntimeError("connection reset"), 3) == 8


def test_editorial_capacity_failure_is_requeued_once_for_global_endpoint_deployment() -> None:
    job_data = {
        "current_stage": "editorial_strategy",
        "last_error": {"message": "429 RESOURCE_EXHAUSTED: Resource exhausted. Please try again later."},
    }

    repair_field = editorial_deployment_repair_field(job_data)

    assert repair_field == "editorial_global_capacity_v1_retry_at"
    job_data[repair_field] = "2026-08-24T00:00:00+00:00"
    assert editorial_deployment_repair_field(job_data) is None


def test_vertex_text_generation_prefers_global_with_regional_failover() -> None:
    assert vertex_text_locations(
        Settings(
            provider_mode="live",
            google_cloud_project="test-project",
            google_cloud_location="us-central1",
        )
    ) == ["global", "us-central1"]


def test_editorial_generation_falls_back_to_regional_endpoint_when_global_is_exhausted(monkeypatch) -> None:
    calls: list[str | None] = []
    payload = editorial_payload()

    class FakeModels:
        def __init__(self, location: str | None):
            self.location = location

        def generate_content(self, **_kwargs):
            calls.append(self.location)
            if self.location == "global":
                raise RuntimeError("429 RESOURCE_EXHAUSTED: Resource exhausted. Please try again later.")
            return SimpleNamespace(text=json.dumps(payload))

    monkeypatch.setattr(
        "apps.api.app.providers.google_genai_client",
        lambda _settings, *, location=None: SimpleNamespace(models=FakeModels(location)),
    )
    provider = EditorialProvider(
        Settings(
            provider_mode="live",
            google_cloud_project="test-project",
            google_cloud_location="us-central1",
        )
    )
    packet = ResearchPacket(
        request_id="research_capacity_failover",
        objective="Explain reusable learning",
        sources=[{"id": "source_1", "title": "Evidence"}],
        claims=[],
        raw={},
    )

    package = provider._generate_with_gemini(
        "Reusable expertise",
        "Independent teachers",
        "awareness",
        {"identity": {"name": "SubSchool"}},
        packet,
        8,
        "ugc_creator",
        False,
        False,
        "",
        ["9:16"],
        "",
        "educational_explainer",
        {},
        "",
        2,
        2,
        0,
    )

    assert calls == ["global", "us-central1"]
    assert len(package["storyboard"]["scenes"]) == 2


def test_continuous_ugc_layout_uses_one_opening_and_seven_second_extensions() -> None:
    layout = continuous_ugc_scene_layout(30, allowed_min=4, allowed_max=6)

    assert layout == [4.0, 7.0, 7.0, 7.0, 5.0]
    assert sum(layout) == 30


def test_candidate_mix_covers_three_intents_and_four_video_formats() -> None:
    candidates = [
        {
            "title": f"Candidate {index}",
            "candidate_type": "problem_solution",
            "recommended_visual_mode": "ugc_creator",
            "suitable_visual_modes": ["ugc_creator", "storytelling", "cinematic", "motion_graphics"],
        }
        for index in range(6)
    ]

    balanced = _rebalance_candidate_mix(candidates, 6)

    assert {item["candidate_type"] for item in balanced} == {
        "problem_solution",
        "educational_value",
        "entertaining_viral",
    }
    assert {item["recommended_visual_mode"] for item in balanced} == {
        "ugc_creator",
        "storytelling",
        "cinematic",
        "motion_graphics",
    }


def test_prompt_sanitizer_removes_renderable_ui_and_palette_tokens() -> None:
    cleaned = _strip_prompt_tokens("Show the platform UI in #A24CB8 with kinetic typography")

    assert "#A24CB8" not in cleaned
    assert " UI " not in f" {cleaned} "
    assert "kinetic typography" not in cleaned.lower()


@pytest.mark.asyncio
async def test_mock_editorial_package_carries_candidate_strategy_into_detailed_scenes() -> None:
    provider = EditorialProvider(Settings(provider_mode="mock"))
    packet = ResearchPacket(
        request_id="research_test",
        objective="Help independent teachers package expertise",
        sources=[{"id": "source_1", "title": "Evidence"}],
        claims=[{"id": "claim_1", "status": "supported", "claim": "Reusable lessons reduce repetition"}],
        raw={},
    )

    package = await provider.create_package(
        title="Stop rebuilding the same lesson",
        audience="Independent teachers",
        objective="awareness",
        brand={"identity": {"name": "SubSchool"}},
        evidence=packet,
        duration_seconds=30,
        visual_mode="ugc_creator",
        native_audio=True,
        continue_scenes=True,
        aspect_ratios=["9:16"],
        creative_context={
            "candidate_type": "problem_solution",
            "target_audience_insight": "Teachers lose evenings repeating delivery work",
            "problem_or_tension": "A live lesson disappears after one cohort",
            "core_message": "Turn one explanation into a reusable learning experience",
            "informational_value": "A concrete packaging sequence",
            "virality_mechanism": "An instantly recognizable late-night teacher moment",
            "creative_direction": "Follow a teacher from a noisy class to an organized worktable",
        },
        scene_count_min=4,
        scene_count_max=6,
        scene_count_flex=0,
    )

    assert package["production_brief"]["audience_insight"].startswith("Teachers lose")
    assert [scene["duration_target"] for scene in package["storyboard"]["scenes"]] == [4, 7, 7, 7, 5]
    assert all(scene["story_beat"] and scene["blocking"] and scene["sound_direction"] for scene in package["storyboard"]["scenes"])
    scenes = package["storyboard"]["scenes"]
    assert scenes[0]["generation_strategy"] == "continuation_track_root"
    assert all(scene["generation_strategy"] == "character_track_extension" for scene in scenes[1:])
    assert {scene["continuation_track"] for scene in scenes} == {"creator"}
    assert all("No fade, dissolve" in scene["visual_prompt"] for scene in scenes)
    assert all("transition sound" in scene["visual_prompt"] for scene in scenes)


@pytest.mark.asyncio
async def test_storytelling_builds_independent_continuation_branches_per_role() -> None:
    provider = EditorialProvider(Settings(provider_mode="mock"))
    packet = ResearchPacket(
        request_id="research_story_tracks",
        objective="Show a teacher and colleague improving a course",
        sources=[{"id": "source_1", "title": "Evidence"}],
        claims=[{"id": "claim_1", "status": "supported", "claim": "Reusable lessons reduce repetition"}],
        raw={},
    )

    package = await provider.create_package(
        title="Stop rebuilding the same lesson",
        audience="Independent teachers",
        objective="awareness",
        brand={"identity": {"name": "SubSchool"}},
        evidence=packet,
        duration_seconds=40,
        visual_mode="storytelling",
        native_audio=True,
        continue_scenes=True,
        aspect_ratios=["9:16"],
        scene_count_min=5,
        scene_count_max=8,
        scene_count_flex=0,
    )

    scenes = package["storyboard"]["scenes"]
    assert sum(scene["duration_target"] for scene in scenes) == 40
    assert [scene["continuation_track"] for scene in scenes[:4]] == ["maya", "leo", "maya", "leo"]
    assert [scene["continuation_track_position"] for scene in scenes[:4]] == [1, 1, 2, 2]
    assert scenes[0]["generation_strategy"] == scenes[1]["generation_strategy"] == "continuation_track_root"
    assert scenes[2]["generation_strategy"] == scenes[3]["generation_strategy"] == "character_track_extension"
    assert {item["key"] for item in package["storyboard"]["character_map"]} == {"maya", "leo"}


def test_live_candidate_generation_uses_json_mode_without_vertex_response_schema(monkeypatch) -> None:
    calls: list[object] = []
    candidates = [
        {
            "title": f"Candidate {index}",
            "angle": f"Filmable angle {index}",
            "audience": "Independent teachers",
            "source_ids": ["source_1"],
            "candidate_type": ("problem_solution", "educational_value", "entertaining_viral")[index % 3],
            "recommended_visual_mode": ("ugc_creator", "storytelling", "cinematic", "motion_graphics")[index],
            "suitable_visual_modes": [("ugc_creator", "storytelling", "cinematic", "motion_graphics")[index]],
        }
        for index in range(4)
    ]

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs["config"])
            if len(calls) == 1:
                return SimpleNamespace(text="not-json")
            return SimpleNamespace(text=json.dumps({"candidates": candidates}))

    monkeypatch.setattr(
        "apps.api.app.providers.google_genai_client",
        lambda _settings: SimpleNamespace(models=FakeModels()),
    )
    provider = TopicCandidateProvider(
        Settings(
            provider_mode="live",
            google_cloud_project="test-project",
        )
    )
    packet = ResearchPacket(
        request_id="research_schema_test",
        objective="Find useful course creator topics",
        sources=[{"id": "source_1", "title": "Primary evidence"}],
        claims=[],
        raw={},
    )

    result = provider._generate_with_gemini(
        "Find useful course creator topics",
        {"audiences": {"primary": ["Independent teachers"]}},
        packet,
        4,
        {},
    )

    assert len(calls) == 2
    assert all(getattr(config, "response_schema", None) is None for config in calls)
    assert {item["recommended_visual_mode"] for item in result} == {
        "ugc_creator",
        "storytelling",
        "cinematic",
        "motion_graphics",
    }
    assert all(item["core_message"] and item["creative_direction"] for item in result)
