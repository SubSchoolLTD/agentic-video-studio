from __future__ import annotations

import json

from apps.api.app.database import SessionLocal
from apps.api.app.providers import EditorialPackage
from apps.api.app.repository import ResourceRepository
from apps.api.app.workflow import editorial_deployment_repair_field


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
