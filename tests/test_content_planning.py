from __future__ import annotations

import json
import math
from collections import Counter
from types import SimpleNamespace

import pytest

from apps.api.app.config import Settings, get_settings
from apps.api.app.content_planning import content_quotas, research_plan, select_content_candidates
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.providers import EditorialProvider, ResearchPacket, TopicCandidateProvider
from apps.api.app.repository import ResourceRepository
from apps.api.app.routes import _enqueue_automatic_candidate_productions, _run_research_task


@pytest.mark.parametrize("count", [1, 2, 3, 7, 50])
def test_content_quotas_round_without_losing_slots_or_adding_zero_share_types(count):
    quotas = content_quotas(count, {"selling": 0, "viral": 30, "informative": 70})
    assert sum(quotas.values()) == count
    assert quotas["problem_solution"] == 0
    assert abs(quotas["entertaining_viral"] - count * 0.3) < 1


def test_automatic_selection_uses_mix_then_score_and_corrects_past_imbalance():
    pool = [SimpleNamespace(id=f"{kind}-{index}", data={"candidate_type": kind, "topic_opportunity_score": 100 - index})
            for kind in ("problem_solution", "entertaining_viral", "educational_value") for index in range(12)]
    mix = {"selling": 20, "viral": 30, "informative": 50}
    selected = select_content_candidates(pool, 10, mix, [])
    assert Counter(item.data["candidate_type"] for item in selected) == content_quotas(10, mix)
    assert {item.id for item in selected if item.data["candidate_type"] == "problem_solution"} == {
        "problem_solution-0", "problem_solution-1",
    }
    corrected = select_content_candidates(pool, 6, mix, ["problem_solution"] * 4)
    assert not any(item.data["candidate_type"] == "problem_solution" for item in corrected)
    assert len(select_content_candidates(pool, 3, {"informative": 100}, [])) == 3


@pytest.mark.parametrize("target", [8, 60, 120, 3600])
async def test_mock_research_obeys_project_duration_and_mix(target):
    brand = {"project_context": {"average_duration_seconds": target, "content_mix": {"informative": 100}}}
    packet = ResearchPacket("fixture", "Useful examples", [], [], {})
    items = await TopicCandidateProvider(Settings(provider_mode="mock")).propose(
        objective="Useful examples", brand=brand, evidence=packet, max_candidates=5,
    )
    assert {item["recommended_duration_seconds"] for item in items} == {target}
    assert {item["candidate_type"] for item in items} == {"educational_value"}
    assert all(item["recommended_scene_count_min"] >= math.ceil(target / 8) for item in items)


def test_live_research_repairs_short_candidates_and_wrong_intents(monkeypatch):
    prompts = []

    def generate_content(**kwargs):
        prompt = json.loads(kwargs["contents"])
        prompts.append(prompt)
        plan = prompt["required_production_plan"]
        kinds = [kind for kind, quota in plan["candidate_type_counts"].items() for _ in range(quota)]
        return SimpleNamespace(text=json.dumps({"candidates": [
            {"title": f"Idea {index}", "angle": "Detailed actionable lesson", "audience": "Teachers",
             "candidate_type": kind if len(prompts) > 1 else "problem_solution",
             "recommended_duration_seconds": 60 if len(prompts) > 1 else 25,
             "recommended_visual_mode": ("ugc_creator", "storytelling", "cinematic", "motion_graphics")[index % 4]}
            for index, kind in enumerate(kinds)
        ]}))

    monkeypatch.setattr("apps.api.app.providers.google_genai_client", lambda *_args, **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content),
    ))
    brand = {"project_context": {"average_duration_seconds": 60, "content_mix": {"selling": 20, "viral": 30, "informative": 50}}}
    result = TopicCandidateProvider(Settings(provider_mode="live"))._generate_with_gemini(
        "New topics", brand, ResearchPacket("test", "New topics", [], [], {}), 10, {},
    )
    assert len(prompts) == 2
    assert "60-second target" in prompts[1]["repair_instruction"]
    assert "intent counts" in prompts[1]["repair_instruction"]
    assert Counter(item["candidate_type"] for item in result) == research_plan(brand, 10)["candidate_type_counts"]
    assert all(item["recommended_duration_seconds"] == 60 and item["recommended_scene_count_min"] >= 8 for item in result)


def test_invalid_content_plan_is_not_silently_relabelled_or_stretched(monkeypatch):
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps({"candidates": [{
            "title": "Too short", "angle": "A tiny sketch", "audience": "Teachers",
            "candidate_type": "problem_solution", "recommended_duration_seconds": 20,
        }]}))

    monkeypatch.setattr("apps.api.app.providers.google_genai_client", lambda *_args, **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content),
    ))
    with pytest.raises(RuntimeError, match="did not satisfy the content plan"):
        TopicCandidateProvider(Settings(provider_mode="live"))._generate_with_gemini(
            "Topics", {"project_context": {"average_duration_seconds": 60, "content_mix": {"informative": 100}}},
            ResearchPacket("test", "Topics", [], [], {}), 1, {},
        )
    assert len(calls) == 3


def test_review_keeps_client_alive_through_request(monkeypatch):
    models = []

    class FakeModels:
        closed = False

        def generate_content(self, **_kwargs):
            assert not self.closed, "Cannot send a request, as the client has been closed."
            return SimpleNamespace(parsed=None, text=json.dumps({
                "approved": True, "score": 90, "valuable": True, "interesting": True,
                "commercially_effective": True, "logically_coherent": True, "product_accurate": True,
            }))

    class OwnedClient:
        def __init__(self):
            self.models = FakeModels()
            models.append(self.models)

        def __del__(self):
            self.models.closed = True

    monkeypatch.setattr("apps.api.app.providers.google_genai_client", lambda *_args, **_kwargs: OwnedClient())
    result = EditorialProvider(Settings(provider_mode="live"))._review_package_with_gemini(
        {}, {}, "Useful lesson", "Teachers", "education",
    )
    assert result["approved"] is True
    assert len(models) == 1


async def test_research_propagates_saved_preferences_and_automation_respects_weekly_cap(client, monkeypatch):
    scheduled = []
    monkeypatch.setattr(app.state.workflow, "schedule", lambda job_id: scheduled.append(job_id))
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        project = repo.add(kind="project", organization_id="org_demo", project_id=None, data={
            "name": "Minute-long content", "automation_mode": "scripts",
            "settings": {"content_mix": {"selling": 20, "viral": 30, "informative": 50},
                         "production": {"average_duration_seconds": 60, "videos_per_week": 10}},
        })
        run = repo.add(kind="research_run", organization_id="org_demo", project_id=project.id,
                       data={"objective": "Useful minute-long lessons", "max_candidates": 30})
        run_id = run.id
    await _run_research_task(run_id, get_settings())
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        run = repo.get_any(run_id)
        assert run.status == "completed", run.data.get("error")
        assert run.data["content_plan"]["average_duration_seconds"] == 60
        candidates = repo.list(organization_id="org_demo", project_id=project.id, kind="topic_candidate")
        assert len(candidates) == 30
        assert Counter(item.data["candidate_type"] for item in candidates) == content_quotas(30, {"selling": 20, "viral": 30, "informative": 50})
        assert {item.data["recommended_duration_seconds"] for item in candidates} == {60}
        jobs = repo.list(organization_id="org_demo", project_id=project.id, kind="generation_job")
        assert len(jobs) == len(scheduled) == 10
        assert Counter(item.data["candidate_type"] for item in jobs) == content_quotas(10, {"selling": 20, "viral": 30, "informative": 50})
        assert all(item.data["target_duration_seconds"] == 60 and item.data["scene_count_min"] >= 8 for item in jobs)
        assert all(item.data["generation_start_mode"] == "review_script" for item in jobs)
        assert _enqueue_automatic_candidate_productions(session, repo, run, run.data["candidate_ids"], get_settings()) == []
        assert len(scheduled) == 10
