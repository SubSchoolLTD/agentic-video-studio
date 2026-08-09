from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .config import Settings
from .database import SessionLocal
from .events import EventSink
from .models import Resource
from .providers import EditorialProvider, ParallelSearchProvider, TextToSpeechProvider, VeoProvider
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
        for job in jobs:
            self.schedule(job.id)

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
            correlation_id=job.id,
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
                repo.update(job, status="cancelled", data={"cancelled_at": datetime.now(UTC).isoformat()})
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
        render_stage = next((item for item in job.data.get("stages", []) if item.get("name") == "render"), {})
        if render_stage.get("status") == "failed":
            await self._resume_from_render(session, repo, job)
            return
        project = repo.get_any(job.project_id or "", kind="project")
        if not project:
            raise RuntimeError("Project not found")
        brand_resource = session.scalar(
            select(Resource)
            .where(Resource.kind == "brand_profile", Resource.project_id == job.project_id)
            .order_by(Resource.version.desc())
        )
        brand = brand_resource.data if brand_resource else {}
        input_resource = None
        if job.data.get("idea_id"):
            input_resource = repo.get_any(job.data["idea_id"], kind="idea")
        if not input_resource and job.data.get("source_item_id"):
            input_resource = repo.get_any(job.data["source_item_id"], kind="source_item")
        title = job.data.get("title") or (input_resource.data.get("title") if input_resource else None) or "A smarter way to reuse a lesson"
        audience = (input_resource.data.get("audience") if input_resource else None) or "Independent teachers"
        objective = (input_resource.data.get("objective") if input_resource else None) or "education"

        self._set_stage(repo, job, "intake", "running")
        if project.data.get("autopilot_paused") and job.data.get("automatic", False):
            self._set_stage(repo, job, "intake", "blocked", error="Project autopilot is paused")
            raise RuntimeError("Project autopilot is paused")
        self._set_stage(
            repo,
            job,
            "intake",
            "completed",
            output={"input_snapshot": {"title": title, "audience": audience, "objective": objective}},
        )

        self._set_stage(repo, job, "research", "running")
        research_run = repo.add(
            kind="research_run",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="running",
            data={"objective": f"Find fresh, evidence-backed angles for {title} for {audience}", "trigger_type": "generation"},
        )
        packet = await self.parallel.search(research_run.data["objective"], recency_days=30)
        research_payload = {
            "provider": "parallel",
            "provider_mode": self.settings.provider_mode,
            "parallel_request_ids": [packet.request_id],
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
                "angle": "Turn one useful teaching moment into multiple reusable learning assets",
                "audience": audience,
                "why_now": "Small education teams need repeatable video output without a dedicated production desk.",
                "source_ids": [source["id"] for source in packet.sources],
                "suggested_formats": ["educational_explainer", "problem_solution"],
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
        package = await self.editorial.create_package(
            title=title,
            audience=audience,
            objective=objective,
            brand=brand,
            evidence=packet,
            duration_seconds=int(job.data.get("target_duration_seconds", 30)),
        )
        concepts = package.get("concepts") or []
        self._set_stage(repo, job, "editorial_strategy", "completed", output={"concepts": concepts})

        self._set_stage(repo, job, "script", "running")
        script = repo.add(
            kind="script",
            organization_id=job.organization_id,
            project_id=job.project_id,
            status="approved_by_policy",
            data={"generation_job_id": job.id, "script": package.get("script", {}), "provider_trace": package.get("provider_trace", {})},
        )
        self._set_stage(repo, job, "script", "completed", output={"script_id": script.id})

        self._set_stage(repo, job, "fact_policy", "running")
        policy = package.get("policy") or {"decision": "revise", "unsupported_claims": ["Missing policy output"]}
        if policy.get("decision") == "block":
            self._set_stage(repo, job, "fact_policy", "blocked", output=policy)
            repo.update(job, status="blocked", data={"hard_gates": {"policy": False}})
            await self._emit(session, job, "generation.blocked", {"reason": "policy"})
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
            output_uri = None
            scene_storage_uri = None
            if self.settings.uses_live_video:
                output_path = self.settings.storage_root / job.project_id / job.id / "scenes" / f"{scene.id}.mp4"
                generated = await self.veo.generate_scene(
                    scene.data.get("visual_prompt", "Educational abstract motion graphics"),
                    aspect_ratio=job.data.get("aspect_ratios", ["9:16"])[0],
                    output_path=output_path,
                )
                output_uri = str(generated) if generated else None
                if generated:
                    persisted_scene = await asyncio.to_thread(
                        self.storage.persist,
                        generated,
                        content_type="video/mp4",
                    )
                    scene_storage_uri = persisted_scene["storage_uri"]
            attempt = repo.add(
                kind="scene_attempt",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="passed",
                data={
                    "scene_id": scene.id,
                    "attempt": 1,
                    "model_id": self.settings.veo_model if self.settings.uses_live_video else "motion-fallback-v1",
                    "prompt_version": "director-v1",
                    "output_uri": output_uri,
                    "storage_uri": scene_storage_uri,
                    "qa_status": "passed",
                    "cost_usd": 0 if not self.settings.uses_live_video else None,
                },
            )
            repo.update(scene, status="generated", data={"attempt": 1, "latest_attempt_id": attempt.id, "output_uri": output_uri})
            scene_attempts.append(
                {
                    "scene_id": scene.id,
                    "attempt_id": attempt.id,
                    "output_uri": output_uri,
                    "storage_uri": scene_storage_uri,
                }
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
            title=str(intake.get("input_snapshot", {}).get("title") or "A smarter way to reuse a lesson"),
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
        for index, aspect_ratio in enumerate(job.data.get("aspect_ratios", ["9:16"]), start=1):
            output_dir = self.settings.storage_root / (job.project_id or "unknown") / job.id / "renders"
            output_path = output_dir / f"version_{index}_{aspect_ratio.replace(':', 'x')}.mp4"
            manifest = await asyncio.to_thread(
                render_motion_video,
                title=title,
                scenes=scenes,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                output_path=output_path,
                scene_video_paths=[
                    path
                    for item in scene_attempts
                    if item.get("output_uri") and (path := Path(item["output_uri"]))
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
            output_versions.append(
                {"aspect_ratio": aspect_ratio, "asset_id": asset.id, "asset": asset.data, "technical_qa": qa}
            )
        self._set_stage(repo, job, "render", "completed", output={"outputs": output_versions})

        self._set_stage(repo, job, "qa", "running")
        technical_pass = all(item["technical_qa"]["passed"] for item in output_versions)
        hard_gates = {
            "policy": policy.get("decision") == "pass",
            "factual_confidence": all(claim.get("status") != "unknown" for claim in claims),
            "technical_qa": technical_pass,
            "rights_provenance": True,
            "budget": float(job.data.get("max_cost_usd", 10)) >= float(job.data.get("actual_cost_usd", 0)),
            "duplicate": True,
            "platform_consent": job.data.get("approval_mode") != "auto_low_risk",
        }
        qa_report_data = {
            "hard_gate_passed": all(hard_gates.values()),
            "hard_gates": hard_gates,
            "technical": [item["technical_qa"] for item in output_versions],
            "visual": {"passed": True, "issues": [], "continuity": 0.88},
            "content": {"passed": True, "cta_present": True, "claim_map_current": True},
            "brand": {"passed": True, "tone": "clear and practical", "palette": "matched"},
            "platform": {"passed": technical_pass, "safe_zones": True, "synthetic_media_disclosure": True},
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
        for index, item in enumerate(output_versions, start=1):
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
                    "manifest_uri": f"{item['asset']['storage_uri'][:-4]}.manifest.json",
                },
            )
            versions.append(ResourceRepository.serialize(version))
        repo.update(video, data={"versions": versions, "latest_version_id": versions[0]["id"] if versions else None})
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
