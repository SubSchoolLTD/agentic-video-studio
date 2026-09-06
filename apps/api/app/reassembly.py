"""Render an explicit edit-decision list. This path never calls Veo."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from .database import SessionLocal
from .models import Resource
from .repository import ResourceRepository

if TYPE_CHECKING:
    from .workflow import WorkflowManager


async def run_reassembly(workflow: WorkflowManager, operation_id: str) -> None:
    with SessionLocal() as session:
        operation = session.scalar(
            select(Resource)
            .where(
                Resource.id == operation_id,
                Resource.kind == "video_reassembly",
            )
            .with_for_update(skip_locked=True)
        )
        if not operation or operation.status in {"completed", "failed", "cancelled"}:
            return
        if operation.status == "running" and operation.updated_at.replace(tzinfo=UTC) > datetime.now(
            UTC
        ) - timedelta(minutes=15):
            return
        repo = ResourceRepository(session)
        repo.update(operation, status="running")
        job = repo.get(
            str(operation.data["generation_job_id"]),
            organization_id=operation.organization_id,
            project_id=operation.project_id,
            kind="generation_job",
        )
        if not job or job.data.get("active_reassembly_id") != operation.id:
            repo.update(
                operation, status="failed", data={"error": "The production no longer owns this assembly"}
            )
            return
        try:
            workflow._set_stage(repo, job, "voice_audio", "running")
            scenes, attempts = [], []
            for scene_id in operation.data["scene_ids"]:
                scene = repo.get(
                    scene_id,
                    organization_id=operation.organization_id,
                    project_id=operation.project_id,
                    kind="scene",
                )
                take = repo.get(
                    operation.data["selection"][scene_id],
                    organization_id=operation.organization_id,
                    project_id=operation.project_id,
                    kind="scene_attempt",
                )
                if not scene or not take or take.status != "passed" or take.data.get("scene_id") != scene_id:
                    raise RuntimeError("A selected scene take is no longer available")
                # Original attempts store narration and compiled prompts. New
                # attempts also store the authored scene snapshot for accurate history.
                snapshot = {
                    **scene.data,
                    **(take.data.get("scene_snapshot") or {}),
                    "narration": take.data.get("narration", scene.data.get("narration", "")),
                    "visual_prompt": take.data.get("visual_prompt", scene.data.get("visual_prompt", "")),
                }
                scenes.append(snapshot)
                attempts.append({**take.data, "attempt_id": take.id})
                await asyncio.to_thread(
                    workflow.storage.materialize,
                    storage_uri=take.data["storage_uri"],
                    local_path=Path(take.data["output_uri"]),
                )
            native_audio = job.data.get("audio_mode") == "veo_native"
            audio_path = None
            if workflow.settings.uses_live_video and not native_audio and not job.data.get("test_mode"):
                voiceover = " ".join(
                    str(scene.get("narration") or "")
                    for scene in scenes
                    if scene.get("speaker_kind") != "silent"
                ).strip()
                if voiceover:
                    audio_path = await workflow.tts.synthesize(
                        voiceover,
                        output_path=workflow.settings.storage_root
                        / str(job.project_id)
                        / job.id
                        / "audio"
                        / operation.id
                        / "voiceover.wav",
                    )
            persisted_audio = (
                await asyncio.to_thread(workflow.storage.persist, audio_path, content_type="audio/wav")
                if audio_path
                else {}
            )
            captions = await workflow._persist_caption_assets(
                repo=repo, job=job, scenes=scenes, artifact_key=operation.id
            )
            workflow._set_stage(
                repo,
                job,
                "voice_audio",
                "completed",
                output={
                    "provider": "veo_native_audio"
                    if native_audio
                    else "google_tts"
                    if audio_path
                    else "deterministic_audio_bed",
                    "audio_path": str(audio_path) if audio_path else None,
                    "audio_storage_uri": persisted_audio.get("storage_uri"),
                    "caption_asset_id": captions["vtt"],
                    "caption_srt_asset_id": captions["srt"],
                    "timestamps": True,
                },
            )
            script_stage = workflow._completed_stage_output(job, "script")
            original_script = repo.get_any(script_stage["script_id"], kind="script")
            if not original_script:
                raise RuntimeError("The original script checkpoint is unavailable")
            script = repo.add(
                kind="script",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="complete",
                data={
                    **original_script.data,
                    "reassembly_id": operation.id,
                    "script": {
                        **original_script.data.get("script", {}),
                        "beats": scenes,
                        "voiceover": " ".join(str(scene.get("narration") or "") for scene in scenes),
                    },
                },
            )
            research = workflow._completed_stage_output(job, "research")
            research_run = repo.get_any(research["research_run_id"], kind="research_run")
            candidate = repo.get_any(research["candidate_id"], kind="topic_candidate")
            if not research_run or not candidate:
                raise RuntimeError("Research checkpoints are unavailable")
            await workflow._complete_from_render(
                session=session,
                repo=repo,
                job=job,
                title=str(
                    job.data.get("title") or original_script.data.get("script", {}).get("title") or "Video"
                ),
                scenes=scenes,
                scene_attempts=attempts,
                audio_path=audio_path,
                policy=workflow._completed_stage_output(job, "fact_policy"),
                claims=list(research_run.data.get("claims") or []),
                source_count=int(
                    research_run.data.get("source_count") or len(research_run.data.get("sources") or [])
                ),
                opportunity_score=int(candidate.data.get("topic_opportunity_score") or 0),
                script_id=script.id,
                storyboard_id=workflow._completed_stage_output(job, "storyboard")["storyboard_id"],
                scene_ids=operation.data["scene_ids"],
                caption_asset_id=captions["vtt"],
                caption_srt_asset_id=captions["srt"],
                research_run_id=research_run.id,
                reassembly=operation,
            )
            repo.update(
                operation,
                status="completed",
                data={
                    "video_version_ids": job.data.get("video_version_ids"),
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
            repo.update(
                job,
                data={
                    "active_reassembly_id": None,
                    "last_reassembly_error": None,
                    "last_regeneration_error": None,
                },
            )
        except asyncio.CancelledError:
            # A graceful Cloud Run restart can resume without starting any Veo work.
            repo.update(operation, status="queued", data={"interrupted_at": datetime.now(UTC).isoformat()})
            repo.update(job, status="queued")
            raise
        except Exception as exc:
            repo.update(operation, status="failed", data={"error": str(exc)})
            workflow._set_stage(
                repo, job, str(job.data.get("current_stage") or "render"), "failed", error=str(exc)
            )
            repo.update(
                job,
                status="failed",
                data={
                    "active_reassembly_id": None,
                    "last_reassembly_error": str(exc),
                    "last_error": {"message": str(exc)},
                },
            )
