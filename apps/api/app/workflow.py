from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .config import Settings
from .database import SessionLocal
from .events import EventSink
from .models import Resource
from .providers import (
    EditorialProvider,
    MultimodalQAProvider,
    ParallelSearchProvider,
    TextToSpeechProvider,
    VeoProvider,
)
from .renderer import render_motion_video, technical_qa, write_webvtt
from .repository import ResourceRepository
from .scoring import final_scores, topic_score
from .storage import MediaStorage

logger = logging.getLogger("avs.workflow")


STAGES = (
    "intake",
    "research",
    "editorial_strategy",
    "script",
    "fact_policy",
    "storyboard",
    "scene_generation",
    "voice_audio",
    "render",
    "qa",
    "scoring",
)
RESUME_GRACE_SECONDS = 20


def initial_stage_state() -> list[dict[str, Any]]:
    return [
        {"name": name, "status": "pending", "attempt": 0, "started_at": None, "completed_at": None}
        for name in STAGES
    ]


class WorkflowManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.parallel = ParallelSearchProvider(settings)
        self.editorial = EditorialProvider(settings)
        self.multimodal_qa = MultimodalQAProvider(settings)
        self.veo = VeoProvider(settings)
        self.tts = TextToSpeechProvider(settings)
        self.storage = MediaStorage(settings)
        self.events = EventSink(settings)
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, job_id: str) -> None:
        existing = self.tasks.get(job_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self.run(job_id), name=f"generation:{job_id}")
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))

    def schedule_scene_regeneration(self, regeneration_id: str) -> None:
        task_key = f"scene-regeneration:{regeneration_id}"
        existing = self.tasks.get(task_key)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            self.run_scene_regeneration(regeneration_id),
            name=task_key,
        )
        self.tasks[task_key] = task
        task.add_done_callback(lambda _: self.tasks.pop(task_key, None))

    def resume_pending(self) -> None:
        with SessionLocal() as session:
            jobs = list(
                session.scalars(
                    select(Resource).where(
                        Resource.kind == "generation_job",
                        Resource.status.in_(["queued", "running"]),
                    )
                )
            )
        loop = asyncio.get_running_loop()
        for job in jobs:
            loop.call_later(RESUME_GRACE_SECONDS, self.schedule, job.id)
        with SessionLocal() as session:
            regenerations = list(
                session.scalars(
                    select(Resource).where(
                        Resource.kind == "scene_regeneration",
                        Resource.status.in_(["queued", "running"]),
                    )
                )
            )
        for regeneration in regenerations:
            loop.call_later(
                RESUME_GRACE_SECONDS,
                self.schedule_scene_regeneration,
                regeneration.id,
            )

    async def run_scene_regeneration(self, regeneration_id: str) -> None:
        with SessionLocal() as session:
            repo = ResourceRepository(session)
            regeneration = repo.get_any(regeneration_id, kind="scene_regeneration")
            if not regeneration or regeneration.status in {"completed", "cancelled"}:
                return
            scene = repo.get_any(str(regeneration.data.get("scene_id") or ""), kind="scene")
            if not scene:
                repo.update(regeneration, status="failed", data={"error": "Scene not found"})
                return
            storyboard = repo.get_any(str(scene.data.get("storyboard_id") or ""), kind="storyboard")
            job = (
                repo.get_any(str(storyboard.data.get("generation_job_id") or ""), kind="generation_job")
                if storyboard
                else None
            )
            if not storyboard or not job:
                repo.update(regeneration, status="failed", data={"error": "Parent production checkpoint not found"})
                repo.update(scene, status="regeneration_failed")
                return
            if scene.data.get("locked"):
                repo.update(regeneration, status="failed", data={"error": "Scene is locked by approval"})
                repo.update(scene, status="generated")
                return

            repo.update(regeneration, status="running", data={"started_at": datetime.now(UTC).isoformat()})
            prompt = str(regeneration.data.get("visual_prompt") or scene.data.get("visual_prompt") or "").strip()
            if not prompt:
                repo.update(regeneration, status="failed", data={"error": "Scene visual prompt is empty"})
                repo.update(scene, status="regeneration_failed")
                return
            aspect_ratios = list(job.data.get("aspect_ratios") or ["9:16"])
            attempt_number = int(scene.data.get("attempt", 0)) + 1
            replacement_attempts: list[dict[str, Any]] = []
            latest_attempt_ids: dict[str, str] = {}
            output_uris: dict[str, str | None] = {}
            previous_job_state = {
                "status": job.status,
                "current_stage": job.data.get("current_stage"),
                "progress": job.data.get("progress"),
                "stages": job.data.get("stages"),
            }
            try:
                for aspect_ratio in aspect_ratios:
                    output_uri = None
                    storage_uri = None
                    if self.settings.uses_live_video:
                        ratio_slug = aspect_ratio.replace(":", "x")
                        output_path = (
                            self.settings.storage_root
                            / (job.project_id or "unknown")
                            / job.id
                            / "scenes"
                            / f"{scene.id}_attempt_{attempt_number}_{ratio_slug}.mp4"
                        )
                        generated = await self.veo.generate_scene(
                            prompt,
                            aspect_ratio=aspect_ratio,
                            output_path=output_path,
                        )
                        if generated is None:
                            raise RuntimeError(f"Live Veo returned no output for {scene.id} ({aspect_ratio})")
                        output_uri = str(generated)
                        persisted = await asyncio.to_thread(
                            self.storage.persist,
                            generated,
                            content_type="video/mp4",
                        )
                        storage_uri = persisted["storage_uri"]
                    attempt = repo.add(
                        kind="scene_attempt",
                        organization_id=job.organization_id,
                        project_id=job.project_id,
                        status="passed",
                        data={
                            "scene_id": scene.id,
                            "attempt": attempt_number,
                            "aspect_ratio": aspect_ratio,
                            "model_id": self.settings.veo_model if self.settings.uses_live_video else "deterministic-test-fixture",
                            "prompt_version": "editorial-ugc-v2",
                            "visual_prompt": prompt,
                            "output_uri": output_uri,
                            "storage_uri": storage_uri,
                            "qa_status": "pending" if self.settings.uses_live_video else "fixture",
                            "demo_data": not self.settings.uses_live_video,
                            "regeneration_id": regeneration.id,
                        },
                    )
                    latest_attempt_ids[aspect_ratio] = attempt.id
                    output_uris[aspect_ratio] = output_uri
                    replacement_attempts.append(
                        {
                            "scene_id": scene.id,
                            "attempt_id": attempt.id,
                            "aspect_ratio": aspect_ratio,
                            "model_id": attempt.data["model_id"],
                            "demo_data": attempt.data["demo_data"],
                            "output_uri": output_uri,
                            "storage_uri": storage_uri,
                        }
                    )

                generation_output = self._completed_stage_output(job, "scene_generation")
                retained_attempts = [
                    item
                    for item in list(generation_output.get("attempts") or [])
                    if item.get("scene_id") != scene.id
                ]
                updated_generation_output = {"attempts": [*retained_attempts, *replacement_attempts]}
                stages = [dict(item) for item in job.data.get("stages", [])]
                completed_count = 0
                for stage in stages:
                    if stage.get("name") == "scene_generation":
                        stage["status"] = "completed"
                        stage["output"] = updated_generation_output
                        stage["completed_at"] = datetime.now(UTC).isoformat()
                    elif stage.get("name") in {"render", "qa", "scoring"}:
                        stage["status"] = "pending"
                        stage.pop("output", None)
                        stage.pop("error", None)
                    if stage.get("status") == "completed":
                        completed_count += 1
                repo.update(
                    scene,
                    status="generated",
                    data={
                        "attempt": attempt_number,
                        "latest_attempt_id": latest_attempt_ids.get(aspect_ratios[0]),
                        "latest_attempt_ids": latest_attempt_ids,
                        "output_uri": output_uris.get(aspect_ratios[0]),
                        "output_uris": output_uris,
                        "visual_prompt": prompt,
                    },
                )
                repo.update(
                    job,
                    status="running",
                    data={
                        "stages": stages,
                        "current_stage": "render",
                        "progress": round(completed_count / len(stages), 2),
                        "last_error": None,
                    },
                )
                await self._resume_from_render(session, repo, job)
                repo.update(
                    regeneration,
                    status="completed",
                    data={
                        "completed_at": datetime.now(UTC).isoformat(),
                        "attempt_ids": [item["attempt_id"] for item in replacement_attempts],
                        "video_id": job.data.get("video_id"),
                        "video_version_ids": job.data.get("video_version_ids", []),
                    },
                )
            except Exception as exc:
                logger.exception("scene_regeneration_failed", extra={"regeneration_id": regeneration_id})
                repo.update(
                    regeneration,
                    status="failed",
                    data={"error": str(exc), "failed_at": datetime.now(UTC).isoformat()},
                )
                repo.update(scene, status="regeneration_failed", data={"regeneration_error": str(exc)})
                repo.update(
                    job,
                    status=str(previous_job_state["status"]),
                    data={
                        "current_stage": previous_job_state["current_stage"],
                        "progress": previous_job_state["progress"],
                        "stages": previous_job_state["stages"],
                        "last_regeneration_error": str(exc),
                    },
                )

    @staticmethod
    def _set_stage(
        repo: ResourceRepository,
        job: Resource,
        name: str,
        status: str,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        stages = [dict(item) for item in job.data.get("stages", initial_stage_state())]
        now = datetime.now(UTC).isoformat()
        for item in stages:
            if item["name"] != name:
                continue
            item["status"] = status
            if status == "running":
                item["attempt"] = int(item.get("attempt", 0)) + 1
                item["started_at"] = now
            if status in {"completed", "failed", "blocked"}:
                item["completed_at"] = now
            if output is not None:
                item["output"] = output
            if error:
                item["error"] = error
        completed = sum(1 for item in stages if item["status"] == "completed")
        repo.update(
            job,
            status="running" if status not in {"failed", "blocked"} else status,
            data={
                "stages": stages,
                "current_stage": name,
                "progress": round(completed / len(stages), 2),
            },
        )

    async def _emit(self, session: Any, job: Resource, event_type: str, payload: dict[str, Any] | None = None) -> None:
        await self.events.emit(
            session,
            organization_id=job.organization_id,
            project_id=job.project_id,
            event_type=event_type,
            resource_type="generation_job",
            resource_id=job.id,
            payload=payload,
            correlation_id=str(job.data.get("correlation_id") or job.id),
        )

    async def run(self, job_id: str) -> None:
        with SessionLocal() as session:
            repo = ResourceRepository(session)
            job = repo.get_any(job_id, kind="generation_job")
            if not job or job.status in {"ready", "cancelled", "blocked", "failed"}:
                return
            try:
                await self._emit(session, job, "generation.started")
                await self._run_pipeline(session, repo, job)
            except asyncio.CancelledError:
                session.refresh(job)
                if job.status != "cancelled":
                    repo.update(
                        job,
                        status="running",
                        data={"interrupted_at": datetime.now(UTC).isoformat()},
                    )
                raise
            except Exception as exc:
                logger.exception("generation_failed", extra={"job_id": job_id})
                current_stage = job.data.get("current_stage", "intake")
                self._set_stage(repo, job, current_stage, "failed", error=str(exc))
                repo.update(
                    job,
                    status="failed",
                    data={
                        "last_error": {"code": "generation_failed", "message": str(exc), "retryable": True},
                        "failed_at": datetime.now(UTC).isoformat(),
                    },
                )
                await self._emit(session, job, "generation.failed", {"stage": current_stage, "error": str(exc)})

    async def _run_pipeline(self, session: Any, repo: ResourceRepository, job: Resource) -> None:
        stages = {item.get("name"): item for item in job.data.get("stages", [])}
        render_stage = stages.get("render", {})
        voice_stage = stages.get("voice_audio", {})
        scene_stage = stages.get("scene_generation", {})
        storyboard_stage = stages.get("storyboard", {})
        if render_stage.get("status") in {"running", "failed"} and voice_stage.get("status") == "completed":
            await self._resume_from_render(session, repo, job)
            return
        if (
            storyboard_stage.get("output")
            and scene_stage.get("status") in {"running", "failed", "completed"}
            and job.data.get("current_stage") in {"storyboard", "scene_generation", "voice_audio"}
        ):
            await self._resume_from_scene_generation(session, repo, job)
            return
        project = repo.get_any(job.project_id or "", kind="project")
        if not project:
            raise RuntimeError("Project not found")
        brand_resource = session.scalar(
            select(Resource)
            .where(
                Resource.kind == "brand_profile",
                Resource.organization_id == job.organization_id,
                Resource.project_id == job.project_id,
            )
            .order_by(Resource.version.desc())
        )
        brand = brand_resource.data if brand_resource else {}
        input_resource = None
        if job.data.get("idea_id"):
            input_resource = repo.get_any(job.data["idea_id"], kind="idea")
        if not input_resource and job.data.get("source_item_id"):
            input_resource = repo.get_any(job.data["source_item_id"], kind="source_item")
        title = job.data.get("title") or (input_resource.data.get("title") if input_resource else None) or f"Introducing {project.data.get('name', 'this project')}"
        brand_audiences = brand.get("audiences", {}).get("primary") or []
        audience = (input_resource.data.get("audience") if input_resource else None) or (brand_audiences[0] if brand_audiences else "General audience")
        objective = (input_resource.data.get("objective") if input_resource else None) or project.data.get("brief", {}).get("objective") or "awareness"
        requested_hook = str(input_resource.data.get("hook") or "").strip() if input_resource else ""
        content_format = str(input_resource.data.get("format") or "educational_explainer") if input_resource else "educational_explainer"
        supported_visual_modes = {"ugc_creator", "product_demo", "cinematic", "motion_graphics"}
        visual_mode = str(
            job.data.get("visual_mode")
            or (input_resource.data.get("visual_mode") if input_resource else None)
            or "ugc_creator"
        )
        if visual_mode not in supported_visual_modes:
            raise RuntimeError(f"Unsupported visual mode: {visual_mode}")
        aspect_ratios = list(job.data.get("aspect_ratios") or ["9:16"])

        self._set_stage(repo, job, "intake", "running")
        if project.data.get("autopilot_paused") and job.data.get("automatic", False):
            self._set_stage(repo, job, "intake", "blocked", error="Project autopilot is paused")
            raise RuntimeError("Project autopilot is paused")
        repo.update(job, data={"visual_mode": visual_mode})
        self._set_stage(
            repo,
            job,
            "intake",
            "completed",
            output={
                "input_snapshot": {
                    "title": title,
                    "audience": audience,
                    "objective": objective,
                    "visual_mode": visual_mode,
                    "aspect_ratios": aspect_ratios,
                    "requested_hook": requested_hook,
                    "content_format": content_format,
                }
            },
        )

        self._set_stage(repo, job, "research", "running")
        research_run = repo.add(
            kind="research_run",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="running",
            data={"objective": f"Find fresh, evidence-backed angles for {title} for {audience}", "trigger_type": "generation"},
        )
        research_started = time.perf_counter()
        packet = await self.parallel.search(research_run.data["objective"], recency_days=30)
        await self._emit(
            session,
            job,
            "model.call.completed",
            {
                "stage": "research",
                "provider": "parallel",
                "model": "search",
                "request_id": packet.request_id,
                "latency_ms": round((time.perf_counter() - research_started) * 1000),
                "cost_usd": None,
            },
        )
        research_payload = {
            "provider": "parallel",
            "provider_mode": self.settings.provider_mode,
            "parallel_request_ids": [packet.request_id],
            "parallel_result_metadata": packet.raw,
            "objective": packet.objective,
            "sources": packet.sources,
            "claims": packet.claims,
            "source_count": len(packet.sources),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        repo.update(research_run, status="completed", data=research_payload)
        opportunity = topic_score(len(packet.sources))
        candidate = repo.add(
            kind="topic_candidate",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="selected",
            data={
                "research_run_id": research_run.id,
                "title": title,
                "angle": f"A concise, evidence-backed explanation of {title}",
                "audience": audience,
                "why_now": f"The current research packet contains {len(packet.sources)} relevant sources for this production.",
                "source_ids": [source["id"] for source in packet.sources],
                "sources": packet.sources,
                "supported_claims": [claim for claim in packet.claims if claim.get("status") == "supported"],
                "unresolved_questions": [
                    claim.get("claim")
                    for claim in packet.claims
                    if claim.get("status") not in {"supported", "confirmed"}
                ],
                "freshness_expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                "suggested_formats": ["problem_solution", "explainer"],
                "topic_opportunity_score": opportunity["score"],
                "score_confidence": opportunity["confidence"],
                "score_breakdown": opportunity["breakdown"],
                "risk_flags": [],
            },
        )
        self._set_stage(
            repo,
            job,
            "research",
            "completed",
            output={"research_run_id": research_run.id, "candidate_id": candidate.id, "parallel_request_id": packet.request_id},
        )
        await self._emit(session, job, "research.completed", {"research_run_id": research_run.id})

        self._set_stage(repo, job, "editorial_strategy", "running")
        editorial_started = time.perf_counter()
        package = await self.editorial.create_package(
            title=title,
            audience=audience,
            objective=objective,
            brand=brand,
            evidence=packet,
            duration_seconds=int(job.data.get("target_duration_seconds", 30)),
            visual_mode=visual_mode,
            aspect_ratios=aspect_ratios,
            requested_hook=requested_hook,
            content_format=content_format,
        )
        await self._emit(
            session,
            job,
            "model.call.completed",
            {
                "stage": "editorial_strategy",
                "provider": "google",
                "model": self.settings.gemini_model if self.settings.uses_live_research else "mock-gemini",
                "latency_ms": round((time.perf_counter() - editorial_started) * 1000),
                "cost_usd": None,
            },
        )
        concepts = package.get("concepts") or []
        self._set_stage(
            repo,
            job,
            "editorial_strategy",
            "completed",
            output={
                "concepts": concepts,
                "visual_mode": visual_mode,
                "creator_profile": (package.get("storyboard") or {}).get("creator_profile"),
                "visual_bible": (package.get("storyboard") or {}).get("visual_bible", []),
                "prompt_version": (package.get("provider_trace") or {}).get("prompt_version"),
            },
        )

        self._set_stage(repo, job, "script", "running")
        requested_variants = max(1, min(3, int(job.data.get("variants", 1))))
        script_resources: list[Resource] = []
        base_script = {**dict(package.get("script") or {}), **dict(job.data.get("script_override") or {})}
        for index in range(requested_variants):
            concept = concepts[index % len(concepts)] if concepts else {}
            variant_script = {
                **base_script,
                "hook": concept.get("hook") or base_script.get("hook"),
                "variant_title": concept.get("title") or base_script.get("title"),
            }
            script_resources.append(
                repo.add(
                    kind="script",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status="approved_by_policy",
                    version=index + 1,
                    data={
                        "generation_job_id": job.id,
                        "variant_index": index + 1,
                        "script": variant_script,
                        "provider_trace": package.get("provider_trace", {}),
                    },
                )
            )
        script = script_resources[0]
        self._set_stage(
            repo,
            job,
            "script",
            "completed",
            output={
                "script_id": script.id,
                "script_ids": [item.id for item in script_resources],
                "variant_count": len(script_resources),
            },
        )

        self._set_stage(repo, job, "fact_policy", "running")
        policy = package.get("policy") or {"decision": "revise", "unsupported_claims": ["Missing policy output"]}
        unsupported_claims = list(policy.get("unsupported_claims") or [])
        unknown_claims = [claim for claim in packet.claims if claim.get("status") != "supported"]
        evidence_missing = not packet.sources or not packet.claims
        if policy.get("decision") != "pass" or unsupported_claims or unknown_claims or evidence_missing:
            gate = {
                **policy,
                "decision": "block",
                "evidence_missing": evidence_missing,
                "unknown_claim_ids": [claim.get("id") for claim in unknown_claims],
                "media_generation_started": False,
            }
            self._set_stage(repo, job, "fact_policy", "blocked", output=gate)
            repo.update(job, status="blocked", data={"hard_gates": {"policy": False, "factual_confidence": False}})
            await self._emit(session, job, "generation.blocked", {"reason": "fact_policy", **gate})
            return
        self._set_stage(repo, job, "fact_policy", "completed", output=policy)

        self._set_stage(repo, job, "storyboard", "running")
        storyboard_data = package.get("storyboard") or {"scenes": []}
        storyboard = repo.add(
            kind="storyboard",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="approved",
            data={"generation_job_id": job.id, **storyboard_data},
        )
        scenes = list(storyboard_data.get("scenes") or [])
        if not scenes:
            raise RuntimeError("Editorial provider returned no scenes")
        scene_resources: list[Resource] = []
        for index, scene_data in enumerate(scenes):
            scene_data = {**scene_data, "storyboard_id": storyboard.id, "attempt": 0, "locked": bool(scene_data.get("locked"))}
            scene_resources.append(
                repo.add(
                    resource_id=f"{job.id}_scene_{index + 1}",
                    kind="scene",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status="planned",
                    data=scene_data,
                )
            )
        self._set_stage(repo, job, "storyboard", "completed", output={"storyboard_id": storyboard.id, "scene_ids": [item.id for item in scene_resources]})

        self._set_stage(repo, job, "scene_generation", "running")
        scene_attempts: list[dict[str, Any]] = []
        for scene in scene_resources:
            prompt = str(scene.data.get("visual_prompt") or "").strip()
            if not prompt:
                raise RuntimeError(f"Director returned no visual prompt for {scene.id}")
            latest_attempt_ids: dict[str, str] = {}
            output_uris: dict[str, str | None] = {}
            for aspect_ratio in aspect_ratios:
                output_uri = None
                scene_storage_uri = None
                if self.settings.uses_live_video:
                    ratio_slug = aspect_ratio.replace(":", "x")
                    output_path = (
                        self.settings.storage_root
                        / (job.project_id or "unknown")
                        / job.id
                        / "scenes"
                        / f"{scene.id}_{ratio_slug}.mp4"
                    )
                    scene_started = time.perf_counter()
                    generated = await self.veo.generate_scene(
                        prompt,
                        aspect_ratio=aspect_ratio,
                        output_path=output_path,
                    )
                    if generated is None:
                        raise RuntimeError(f"Live Veo returned no output for {scene.id} ({aspect_ratio})")
                    output_uri = str(generated)
                    persisted_scene = await asyncio.to_thread(
                        self.storage.persist,
                        generated,
                        content_type="video/mp4",
                    )
                    scene_storage_uri = persisted_scene["storage_uri"]
                    await self._emit(
                        session,
                        job,
                        "model.call.completed",
                        {
                            "stage": "scene_generation",
                            "provider": "google",
                            "model": self.settings.veo_model,
                            "scene_id": scene.id,
                            "aspect_ratio": aspect_ratio,
                            "latency_ms": round((time.perf_counter() - scene_started) * 1000),
                            "cost_usd": None,
                        },
                    )
                attempt = repo.add(
                    kind="scene_attempt",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status="passed",
                    data={
                        "scene_id": scene.id,
                        "attempt": 1,
                        "aspect_ratio": aspect_ratio,
                        "model_id": self.settings.veo_model if self.settings.uses_live_video else "deterministic-test-fixture",
                        "prompt_version": "editorial-ugc-v2",
                        "visual_prompt": prompt,
                        "output_uri": output_uri,
                        "storage_uri": scene_storage_uri,
                        "qa_status": "pending" if self.settings.uses_live_video else "fixture",
                        "demo_data": not self.settings.uses_live_video,
                        "cost_usd": None,
                    },
                )
                latest_attempt_ids[aspect_ratio] = attempt.id
                output_uris[aspect_ratio] = output_uri
                scene_attempts.append(
                    {
                        "scene_id": scene.id,
                        "attempt_id": attempt.id,
                        "aspect_ratio": aspect_ratio,
                        "model_id": attempt.data["model_id"],
                        "output_uri": output_uri,
                        "storage_uri": scene_storage_uri,
                    }
                )
            repo.update(
                scene,
                status="generated",
                data={
                    "attempt": 1,
                    "latest_attempt_id": latest_attempt_ids.get(aspect_ratios[0]),
                    "latest_attempt_ids": latest_attempt_ids,
                    "output_uri": output_uris.get(aspect_ratios[0]),
                    "output_uris": output_uris,
                },
            )
        self._set_stage(repo, job, "scene_generation", "completed", output={"attempts": scene_attempts})

        self._set_stage(repo, job, "voice_audio", "running")
        audio_path = None
        if self.settings.uses_live_video:
            voiceover = str((package.get("script") or {}).get("voiceover") or " ".join(scene.get("narration", "") for scene in scenes))
            audio_path = await self.tts.synthesize(
                voiceover,
                output_path=self.settings.storage_root / job.project_id / job.id / "audio" / "voiceover.wav",
            )
        audio_storage_uri = None
        if audio_path:
            persisted_audio = await asyncio.to_thread(
                self.storage.persist,
                audio_path,
                content_type="audio/wav",
            )
            audio_storage_uri = persisted_audio["storage_uri"]
        captions_path = write_webvtt(
            scenes=scenes,
            output_path=self.settings.storage_root / job.project_id / job.id / "captions" / "captions.en.vtt",
            duration_seconds=int(job.data.get("target_duration_seconds", 30)),
        )
        persisted_captions = await asyncio.to_thread(
            self.storage.persist,
            captions_path,
            content_type="text/vtt",
        )
        caption_asset = repo.add(
            kind="media_asset",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="ready",
            data={
                "generation_job_id": job.id,
                "type": "captions",
                "storage_uri": persisted_captions["storage_uri"],
                "local_path": persisted_captions["local_path"],
                "public_path": persisted_captions["public_path"],
                "mime_type": "text/vtt",
                "language": "en",
                "rights_status": "owned",
            },
        )
        self._set_stage(
            repo,
            job,
            "voice_audio",
            "completed",
            output={
                "provider": "google_tts" if self.settings.uses_live_video else "deterministic_audio_bed",
                "audio_path": str(audio_path) if audio_path else None,
                "audio_storage_uri": audio_storage_uri,
                "caption_asset_id": caption_asset.id,
                "timestamps": True,
            },
        )

        await self._complete_from_render(
            session=session,
            repo=repo,
            job=job,
            title=title,
            scenes=scenes,
            scene_attempts=scene_attempts,
            audio_path=audio_path,
            policy=policy,
            claims=packet.claims,
            source_count=len(packet.sources),
            opportunity_score=opportunity["score"],
            script_id=script.id,
            storyboard_id=storyboard.id,
            scene_ids=[item.id for item in scene_resources],
            caption_asset_id=caption_asset.id,
            research_run_id=research_run.id,
        )

    @staticmethod
    def _completed_stage_output(job: Resource, stage_name: str) -> dict[str, Any]:
        stage = next((item for item in job.data.get("stages", []) if item.get("name") == stage_name), None)
        if not stage or stage.get("status") != "completed" or not isinstance(stage.get("output"), dict):
            raise RuntimeError(f"Cannot resume: {stage_name} checkpoint is incomplete")
        return dict(stage["output"])

    @staticmethod
    def _stage_output(job: Resource, stage_name: str) -> dict[str, Any]:
        stage = next((item for item in job.data.get("stages", []) if item.get("name") == stage_name), None)
        if not stage or not isinstance(stage.get("output"), dict):
            raise RuntimeError(f"Cannot resume: {stage_name} checkpoint is incomplete")
        return dict(stage["output"])

    async def _resume_from_scene_generation(
        self,
        session: Any,
        repo: ResourceRepository,
        job: Resource,
    ) -> None:
        intake = self._stage_output(job, "intake")
        research = self._stage_output(job, "research")
        script_stage = self._stage_output(job, "script")
        policy = self._stage_output(job, "fact_policy")
        storyboard_stage = self._stage_output(job, "storyboard")

        storyboard = repo.get_any(storyboard_stage["storyboard_id"], kind="storyboard")
        research_run = repo.get_any(research["research_run_id"], kind="research_run")
        candidate = repo.get_any(research["candidate_id"], kind="topic_candidate")
        script = repo.get_any(script_stage["script_id"], kind="script")
        scene_resources = [
            repo.get_any(scene_id, kind="scene")
            for scene_id in storyboard_stage.get("scene_ids", [])
        ]
        if not storyboard or not research_run or not candidate or not script or any(scene is None for scene in scene_resources):
            raise RuntimeError("Cannot resume: persisted scene-generation resources are missing")

        scenes = list(storyboard.data.get("scenes") or [])
        typed_scenes = [scene for scene in scene_resources if scene is not None]
        if not scenes or len(scenes) != len(typed_scenes):
            raise RuntimeError("Cannot resume: storyboard scene checkpoint is inconsistent")

        self._set_stage(repo, job, "storyboard", "completed", output=storyboard_stage)
        self._set_stage(repo, job, "scene_generation", "running")
        scene_attempts: list[dict[str, Any]] = []
        aspect_ratios = list(job.data.get("aspect_ratios") or ["9:16"])
        for scene in typed_scenes:
            prompt = str(scene.data.get("visual_prompt") or "").strip()
            if not prompt:
                raise RuntimeError(f"Director returned no visual prompt for {scene.id}")
            latest_attempt_ids = dict(scene.data.get("latest_attempt_ids") or {})
            legacy_attempt_id = scene.data.get("latest_attempt_id")
            if legacy_attempt_id and aspect_ratios[0] not in latest_attempt_ids:
                latest_attempt_ids[aspect_ratios[0]] = str(legacy_attempt_id)
            output_uris = dict(scene.data.get("output_uris") or {})
            attempt_number = int(scene.data.get("attempt", 0))
            started_new_attempt = False
            for aspect_ratio in aspect_ratios:
                latest_attempt_id = latest_attempt_ids.get(aspect_ratio)
                latest_attempt = (
                    repo.get_any(str(latest_attempt_id), kind="scene_attempt")
                    if latest_attempt_id
                    else None
                )
                if scene.status == "generated" and latest_attempt and latest_attempt.status == "passed":
                    output_uri = latest_attempt.data.get("output_uri")
                    storage_uri = latest_attempt.data.get("storage_uri")
                    if output_uri and storage_uri:
                        await asyncio.to_thread(
                            self.storage.materialize,
                            storage_uri=storage_uri,
                            local_path=Path(output_uri),
                        )
                    scene_attempts.append(
                        {
                            "scene_id": scene.id,
                            "attempt_id": latest_attempt.id,
                            "aspect_ratio": aspect_ratio,
                            "model_id": latest_attempt.data.get("model_id"),
                            "output_uri": output_uri,
                            "storage_uri": storage_uri,
                        }
                    )
                    continue

                output_uri = None
                scene_storage_uri = None
                if not started_new_attempt:
                    attempt_number += 1
                    started_new_attempt = True
                if self.settings.uses_live_video:
                    ratio_slug = aspect_ratio.replace(":", "x")
                    output_path = (
                        self.settings.storage_root
                        / (job.project_id or "unknown")
                        / job.id
                        / "scenes"
                        / f"{scene.id}_{ratio_slug}.mp4"
                    )
                    scene_started = time.perf_counter()
                    generated = await self.veo.generate_scene(
                        prompt,
                        aspect_ratio=aspect_ratio,
                        output_path=output_path,
                    )
                    if generated is None:
                        raise RuntimeError(f"Live Veo returned no output for {scene.id} ({aspect_ratio})")
                    output_uri = str(generated)
                    persisted_scene = await asyncio.to_thread(
                        self.storage.persist,
                        generated,
                        content_type="video/mp4",
                    )
                    scene_storage_uri = persisted_scene["storage_uri"]
                    await self._emit(
                        session,
                        job,
                        "model.call.completed",
                        {
                            "stage": "scene_generation",
                            "provider": "google",
                            "model": self.settings.veo_model,
                            "scene_id": scene.id,
                            "aspect_ratio": aspect_ratio,
                            "latency_ms": round((time.perf_counter() - scene_started) * 1000),
                            "cost_usd": None,
                            "resumed": True,
                        },
                    )
                attempt = repo.add(
                    kind="scene_attempt",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status="passed",
                    data={
                        "scene_id": scene.id,
                        "attempt": attempt_number,
                        "aspect_ratio": aspect_ratio,
                        "model_id": self.settings.veo_model if self.settings.uses_live_video else "deterministic-test-fixture",
                        "prompt_version": "editorial-ugc-v2",
                        "visual_prompt": prompt,
                        "output_uri": output_uri,
                        "storage_uri": scene_storage_uri,
                        "qa_status": "pending" if self.settings.uses_live_video else "fixture",
                        "demo_data": not self.settings.uses_live_video,
                        "cost_usd": None,
                    },
                )
                latest_attempt_ids[aspect_ratio] = attempt.id
                output_uris[aspect_ratio] = output_uri
                scene_attempts.append(
                    {
                        "scene_id": scene.id,
                        "attempt_id": attempt.id,
                        "aspect_ratio": aspect_ratio,
                        "model_id": attempt.data["model_id"],
                        "output_uri": output_uri,
                        "storage_uri": scene_storage_uri,
                    }
                )
            repo.update(
                scene,
                status="generated",
                data={
                    "attempt": attempt_number,
                    "latest_attempt_id": latest_attempt_ids.get(aspect_ratios[0]),
                    "latest_attempt_ids": latest_attempt_ids,
                    "output_uri": output_uris.get(aspect_ratios[0]),
                    "output_uris": output_uris,
                },
            )
        self._set_stage(repo, job, "scene_generation", "completed", output={"attempts": scene_attempts})

        self._set_stage(repo, job, "voice_audio", "running")
        audio_path = None
        if self.settings.uses_live_video:
            script_payload = dict(script.data.get("script") or {})
            voiceover = str(script_payload.get("voiceover") or " ".join(scene.get("narration", "") for scene in scenes))
            audio_path = await self.tts.synthesize(
                voiceover,
                output_path=self.settings.storage_root / job.project_id / job.id / "audio" / "voiceover.wav",
            )
        audio_storage_uri = None
        if audio_path:
            persisted_audio = await asyncio.to_thread(
                self.storage.persist,
                audio_path,
                content_type="audio/wav",
            )
            audio_storage_uri = persisted_audio["storage_uri"]
        captions_path = write_webvtt(
            scenes=scenes,
            output_path=self.settings.storage_root / job.project_id / job.id / "captions" / "captions.en.vtt",
            duration_seconds=int(job.data.get("target_duration_seconds", 30)),
        )
        persisted_captions = await asyncio.to_thread(
            self.storage.persist,
            captions_path,
            content_type="text/vtt",
        )
        caption_asset = repo.add(
            kind="media_asset",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="ready",
            data={
                "generation_job_id": job.id,
                "type": "captions",
                "storage_uri": persisted_captions["storage_uri"],
                "local_path": persisted_captions["local_path"],
                "public_path": persisted_captions["public_path"],
                "mime_type": "text/vtt",
                "language": "en",
                "rights_status": "owned",
            },
        )
        self._set_stage(
            repo,
            job,
            "voice_audio",
            "completed",
            output={
                "provider": "google_tts" if self.settings.uses_live_video else "deterministic_audio_bed",
                "audio_path": str(audio_path) if audio_path else None,
                "audio_storage_uri": audio_storage_uri,
                "caption_asset_id": caption_asset.id,
                "timestamps": True,
            },
        )

        await self._complete_from_render(
            session=session,
            repo=repo,
            job=job,
            title=str(intake.get("input_snapshot", {}).get("title") or "Introducing this project"),
            scenes=scenes,
            scene_attempts=scene_attempts,
            audio_path=audio_path,
            policy=policy,
            claims=list(research_run.data.get("claims") or []),
            source_count=int(research_run.data.get("source_count") or len(research_run.data.get("sources") or [])),
            opportunity_score=int(candidate.data.get("topic_opportunity_score") or 0),
            script_id=script.id,
            storyboard_id=storyboard.id,
            scene_ids=[scene.id for scene in typed_scenes],
            caption_asset_id=caption_asset.id,
            research_run_id=research_run.id,
        )

    async def _resume_from_render(self, session: Any, repo: ResourceRepository, job: Resource) -> None:
        intake = self._completed_stage_output(job, "intake")
        research = self._completed_stage_output(job, "research")
        script_stage = self._completed_stage_output(job, "script")
        policy = self._completed_stage_output(job, "fact_policy")
        storyboard_stage = self._completed_stage_output(job, "storyboard")
        generation = self._completed_stage_output(job, "scene_generation")
        voice = self._completed_stage_output(job, "voice_audio")

        storyboard = repo.get_any(storyboard_stage["storyboard_id"], kind="storyboard")
        research_run = repo.get_any(research["research_run_id"], kind="research_run")
        candidate = repo.get_any(research["candidate_id"], kind="topic_candidate")
        if not storyboard or not research_run or not candidate:
            raise RuntimeError("Cannot resume: persisted research or storyboard resources are missing")

        audio_value = voice.get("audio_path")
        scene_attempts = list(generation.get("attempts") or [])
        for item in scene_attempts:
            persisted_attempt = repo.get_any(str(item.get("attempt_id") or ""), kind="scene_attempt")
            if persisted_attempt:
                item.setdefault("aspect_ratio", persisted_attempt.data.get("aspect_ratio"))
                item.setdefault("model_id", persisted_attempt.data.get("model_id"))
                item.setdefault("demo_data", persisted_attempt.data.get("demo_data", False))
            output_uri = item.get("output_uri")
            if output_uri:
                await asyncio.to_thread(
                    self.storage.materialize,
                    storage_uri=item.get("storage_uri"),
                    local_path=Path(output_uri),
                )
        if audio_value:
            await asyncio.to_thread(
                self.storage.materialize,
                storage_uri=voice.get("audio_storage_uri"),
                local_path=Path(audio_value),
            )
        await self._complete_from_render(
            session=session,
            repo=repo,
            job=job,
            title=str(intake.get("input_snapshot", {}).get("title") or "Introducing this project"),
            scenes=list(storyboard.data.get("scenes") or []),
            scene_attempts=scene_attempts,
            audio_path=Path(audio_value) if audio_value else None,
            policy=policy,
            claims=list(research_run.data.get("claims") or []),
            source_count=int(research_run.data.get("source_count") or len(research_run.data.get("sources") or [])),
            opportunity_score=int(candidate.data.get("topic_opportunity_score") or 0),
            script_id=script_stage["script_id"],
            storyboard_id=storyboard.id,
            scene_ids=list(storyboard_stage.get("scene_ids") or []),
            caption_asset_id=voice["caption_asset_id"],
            research_run_id=research_run.id,
        )

    async def _complete_from_render(
        self,
        *,
        session: Any,
        repo: ResourceRepository,
        job: Resource,
        title: str,
        scenes: list[dict[str, Any]],
        scene_attempts: list[dict[str, Any]],
        audio_path: Path | None,
        policy: dict[str, Any],
        claims: list[dict[str, Any]],
        source_count: int,
        opportunity_score: int,
        script_id: str,
        storyboard_id: str,
        scene_ids: list[str],
        caption_asset_id: str,
        research_run_id: str,
    ) -> None:
        self._set_stage(repo, job, "render", "running")
        output_versions: list[dict[str, Any]] = []
        duration_seconds = int(job.data.get("target_duration_seconds", 30))
        project = repo.get_any(job.project_id or "", kind="project")
        brand_name = str(project.data.get("name") if project else "Framewise")
        existing_checksums = {
            str(item.data.get("checksum"))
            for item in repo.list(
                organization_id=job.organization_id,
                project_id=job.project_id,
                kind="media_asset",
                limit=200,
            )
            if item.data.get("type") == "video"
            and item.data.get("checksum")
            and item.data.get("generation_job_id") != job.id
        }
        for index, aspect_ratio in enumerate(job.data.get("aspect_ratios", ["9:16"]), start=1):
            render_started = time.perf_counter()
            output_dir = self.settings.storage_root / (job.project_id or "unknown") / job.id / "renders"
            output_path = output_dir / f"version_{index}_{aspect_ratio.replace(':', 'x')}.mp4"
            manifest = await asyncio.to_thread(
                render_motion_video,
                title=title,
                brand_name=brand_name,
                scenes=scenes,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                output_path=output_path,
                scene_video_paths=[
                    path
                    for item in scene_attempts
                    if item.get("output_uri")
                    and item.get("aspect_ratio") in {None, aspect_ratio}
                    and (path := Path(item["output_uri"]))
                ],
                audio_path=audio_path,
            )
            qa = await asyncio.to_thread(
                technical_qa,
                output_path,
                aspect_ratio=aspect_ratio,
                duration_target=duration_seconds,
            )
            persisted_render = await asyncio.to_thread(
                self.storage.persist,
                output_path,
                content_type="video/mp4",
            )
            visual_qa = await self.multimodal_qa.analyze(
                video_uri=persisted_render["storage_uri"],
                scenes=scenes,
                technical=qa,
            )
            duplicate_passed = manifest["checksum"] not in existing_checksums
            await self._emit(
                session,
                job,
                "media.render.completed",
                {
                    "aspect_ratio": aspect_ratio,
                    "latency_ms": round((time.perf_counter() - render_started) * 1000),
                    "technical_passed": qa["passed"],
                    "multimodal_passed": visual_qa["passed"],
                    "model": visual_qa.get("model_id"),
                },
            )
            await asyncio.to_thread(
                self.storage.persist,
                output_path.with_suffix(".manifest.json"),
                content_type="application/json",
            )
            asset = repo.add(
                kind="media_asset",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="ready",
                data={
                    "generation_job_id": job.id,
                    "type": "video",
                    "storage_uri": persisted_render["storage_uri"],
                    "local_path": persisted_render["local_path"],
                    "public_path": persisted_render["public_path"],
                    "mime_type": "video/mp4",
                    "checksum": manifest["checksum"],
                    "width": manifest["width"],
                    "height": manifest["height"],
                    "duration_ms": duration_seconds * 1000,
                    "provenance": "generated" if self.settings.uses_live_video else "deterministic_mock",
                    "rights_status": "owned",
                },
            )
            existing_checksums.add(manifest["checksum"])
            output_versions.append(
                {
                    "aspect_ratio": aspect_ratio,
                    "asset_id": asset.id,
                    "asset": asset.data,
                    "technical_qa": qa,
                    "multimodal_qa": visual_qa,
                    "duplicate_passed": duplicate_passed,
                }
            )
        self._set_stage(repo, job, "render", "completed", output={"outputs": output_versions})

        self._set_stage(repo, job, "qa", "running")
        technical_pass = all(item["technical_qa"]["passed"] for item in output_versions)
        multimodal_pass = all(item["multimodal_qa"]["passed"] for item in output_versions)
        content_pass = all(item["multimodal_qa"].get("gates", {}).get("content") is True for item in output_versions)
        brand_pass = all(item["multimodal_qa"].get("gates", {}).get("brand") is True for item in output_versions)
        platform_pass = technical_pass and all(
            item["multimodal_qa"].get("gates", {}).get("platform") is True for item in output_versions
        )
        provider_provenance_pass = (
            all(
                item.get("storage_uri")
                and item.get("model_id") == self.settings.veo_model
                and not item.get("demo_data")
                for item in scene_attempts
            )
            if self.settings.uses_live_video
            else all(item.get("model_id") == "deterministic-test-fixture" for item in scene_attempts)
        )
        rights_pass = provider_provenance_pass and all(
            item["multimodal_qa"].get("gates", {}).get("rights") is True for item in output_versions
        )
        duplicate_pass = all(item["duplicate_passed"] for item in output_versions)
        script_resource = repo.get_any(script_id, kind="script")
        script_payload = dict(script_resource.data.get("script") or {}) if script_resource else {}
        cta_present = bool(str(script_payload.get("cta") or "").strip())
        claim_map_current = bool(claims) and all(claim.get("status") == "supported" for claim in claims)
        budget_cost = job.data.get("actual_cost_usd")
        if budget_cost is None:
            budget_cost = job.data.get("provider_cost_estimate_usd")
        if budget_cost is None:
            budget_cost = (job.data.get("estimated_cost") or {}).get("max")
        hard_gates = {
            "policy": policy.get("decision") == "pass",
            "factual_confidence": claim_map_current,
            "technical_qa": technical_pass,
            "multimodal_qa": multimodal_pass,
            "content": content_pass and cta_present,
            "brand": brand_pass,
            "platform": platform_pass,
            "rights_provenance": rights_pass,
            "budget": budget_cost is not None and float(job.data.get("max_cost_usd", 10)) >= float(budget_cost),
            "duplicate": duplicate_pass,
            "platform_consent": job.data.get("approval_mode") != "auto_low_risk",
        }
        qa_report_data = {
            "hard_gate_passed": all(hard_gates.values()),
            "hard_gates": hard_gates,
            "technical": [item["technical_qa"] for item in output_versions],
            "visual": {
                "passed": multimodal_pass,
                "outputs": [item["multimodal_qa"] for item in output_versions],
            },
            "content": {
                "passed": content_pass and cta_present,
                "cta_present": cta_present,
                "claim_map_current": claim_map_current,
            },
            "brand": {
                "passed": brand_pass,
                "evaluated_by": "gemini_multimodal" if self.settings.uses_live_video else "deterministic_test_fixture",
            },
            "platform": {
                "passed": platform_pass,
                "safe_zones": technical_pass,
                "synthetic_media_disclosure": True,
            },
            "rights": {
                "passed": rights_pass,
                "provider_provenance": provider_provenance_pass,
            },
            "duplicate": {"passed": duplicate_pass},
        }
        qa_report = repo.add(
            kind="qa_report",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="passed" if qa_report_data["hard_gate_passed"] else "review_required",
            data={"generation_job_id": job.id, **qa_report_data},
        )
        self._set_stage(repo, job, "qa", "completed", output={"qa_report_id": qa_report.id, **qa_report_data})

        self._set_stage(repo, job, "scoring", "running")
        scores = final_scores(
            source_count=source_count,
            technical_pass=technical_pass,
            policy_pass=policy.get("decision") == "pass",
        )
        score_report = repo.add(
            kind="score_report",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="complete",
            data={
                "generation_job_id": job.id,
                "topic_opportunity": opportunity_score,
                **scores,
                "evaluator_version": "score-v1",
            },
        )
        self._set_stage(repo, job, "scoring", "completed", output={"score_report_id": score_report.id, **scores})

        existing_video_id = job.data.get("revision_of_video_id") or job.data.get("video_id")
        video = repo.get_any(str(existing_video_id), kind="video") if existing_video_id else None
        if video:
            repo.update(
                video,
                status="approval_required",
                data={
                    "latest_generation_job_id": job.id,
                    "title": title,
                    "script_id": script_id,
                    "storyboard_id": storyboard_id,
                    "qa_report_id": qa_report.id,
                    "score_report_id": score_report.id,
                    "scene_ids": scene_ids,
                    "caption_asset_id": caption_asset_id,
                },
            )
        else:
            video = repo.add(
                kind="video",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="approval_required",
                data={
                    "generation_job_id": job.id,
                    "title": title,
                    "script_id": script_id,
                    "storyboard_id": storyboard_id,
                    "qa_report_id": qa_report.id,
                    "score_report_id": score_report.id,
                    "scene_ids": scene_ids,
                    "versions": [],
                    "latest_version_id": None,
                    "caption_asset_id": caption_asset_id,
                },
            )
        versions = []
        existing_versions = list(video.data.get("versions") or [])
        first_version = max((int(item.get("version", 0)) for item in existing_versions), default=0) + 1
        for index, item in enumerate(output_versions, start=first_version):
            version = repo.add(
                kind="video_version",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="approval_required",
                version=index,
                data={
                    "video_id": video.id,
                    "generation_job_id": job.id,
                    "aspect_ratio": item["aspect_ratio"],
                    "duration_ms": duration_seconds * 1000,
                    "render_asset_id": item["asset_id"],
                    "render_url": item["asset"]["public_path"],
                    "checksum": item["asset"]["checksum"],
                    "qa_report_id": qa_report.id,
                    "score_report_id": score_report.id,
                    "script_id": script_id,
                    "storyboard_id": storyboard_id,
                    "supersedes_script_id": job.data.get("supersedes_script_id"),
                    "manifest_uri": f"{item['asset']['storage_uri'][:-4]}.manifest.json",
                },
            )
            versions.append(ResourceRepository.serialize(version))
        repo.update(
            video,
            data={
                "versions": [*existing_versions, *versions],
                "latest_version_id": versions[0]["id"] if versions else video.data.get("latest_version_id"),
            },
        )
        repo.update(
            job,
            status="ready",
            data={
                "progress": 1,
                "current_stage": "completed",
                "video_id": video.id,
                "video_version_ids": [item["id"] for item in versions],
                "research_run_id": research_run_id,
                "score_report_id": score_report.id,
                "qa_report_id": qa_report.id,
                "actual_cost_usd": 0.0 if not self.settings.uses_live_video else job.data.get("actual_cost_usd"),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._emit(
            session,
            job,
            "video.approval_required",
            {"video_id": video.id, "version_ids": [item["id"] for item in versions]},
        )
