from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .billing import refund_feature_charges, settle_feature_charge, veo_request_duration
from .config import Settings
from .database import SessionLocal
from .events import EventSink
from .models import Resource
from .providers import (
    CharacterImageProvider,
    EditorialProvider,
    MultimodalQAProvider,
    ParallelSearchProvider,
    ResearchPacket,
    SpeechQAProvider,
    TextToSpeechProvider,
    VeoProvider,
    native_voice_profile,
)
from .renderer import (
    extract_last_frame,
    prepare_veo_extension_input,
    render_motion_video,
    render_scene_fixture,
    technical_qa,
    write_srt,
    write_webvtt,
)
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
MAX_AUTOMATIC_STAGE_RETRIES = 4
LEGACY_EDITORIAL_SCHEMA_ERROR = "specified schema produces a constraint that has too many states for serving"
EDITORIAL_PAYLOAD_SHAPE_ERROR = "editorial provider returned invalid json twice"
EDITORIAL_PAYLOAD_REPAIR_FIELD = "editorial_payload_normalization_v2_retry_at"
EDITORIAL_GLOBAL_CAPACITY_REPAIR_FIELD = "editorial_global_capacity_v1_retry_at"
EDITORIAL_TARGETED_QUALITY_REPAIR_FIELD = "editorial_targeted_quality_v1_retry_at"
EDITORIAL_STRUCTURED_BEATS_REPAIR_FIELD = "editorial_structured_beats_v1_retry_at"
LEGACY_VEO_EMPTY_RESPONSE_ERROR = "'nonetype' object is not subscriptable"
VEO_EMPTY_RESPONSE_REPAIR_FIELD = "veo_empty_response_v1_retry_at"
VEO_HIGH_LOAD_REPAIR_FIELD = "veo_high_load_v1_retry_at"
NATIVE_SPEECH_EDGE_GATE_ERROR = "native audio speech qa failed"
NATIVE_SPEECH_EDGE_GATE_REPAIR_FIELD = "native_speech_edge_gate_v1_retry_at"
NATIVE_SPEECH_COMPLETION_REPAIR_FIELD = "native_speech_completion_v2_retry_at"
RENDER_SAMPLE_ASPECT_RATIO_REPAIR_FIELD = "render_sample_aspect_ratio_v1_retry_at"


def stable_veo_seed(job_id: str, voice_preset: str) -> int:
    """Keep one reproducible Veo sampling anchor for every scene in a production."""
    digest = hashlib.sha256(f"{job_id}:{voice_preset}".encode()).digest()
    return int.from_bytes(digest[:4], "big", signed=False)


def retryable_generation_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "429",
            "resource_exhausted",
            "deadline_exceeded",
            "temporarily unavailable",
            "service unavailable",
            "connection reset",
            "connection aborted",
            "timed out",
            "timeout",
            "internal server error",
            "status: 'unavailable'",
            "status: \"unavailable\"",
            "veo completed without generated video",
            "veo returned no downloadable video bytes",
            "high load",
            "please try again later",
            "editorial provider returned invalid json",
        )
    )


def generation_retry_delay_seconds(exc: Exception, retry_count: int) -> int:
    """Back off long enough for constrained Vertex LRO slots to become available."""
    message = str(exc).lower()
    if any(marker in message for marker in ("429", "resource_exhausted", "high load", "please try again later")):
        return min(30 * (2**retry_count), 240)
    return min(2**retry_count, 30)


def editorial_deployment_repair_field(job_data: dict[str, Any]) -> str | None:
    """Return a one-shot recovery marker for editorial failures fixed by this deployment."""
    if job_data.get("current_stage") != "editorial_strategy":
        return None
    error_message = str((job_data.get("last_error") or {}).get("message") or "").lower()
    if LEGACY_EDITORIAL_SCHEMA_ERROR in error_message and not job_data.get("editorial_schema_repair_retry_at"):
        return "editorial_schema_repair_retry_at"
    if EDITORIAL_PAYLOAD_SHAPE_ERROR in error_message and not job_data.get(EDITORIAL_PAYLOAD_REPAIR_FIELD):
        return EDITORIAL_PAYLOAD_REPAIR_FIELD
    if (
        any(marker in error_message for marker in ("429", "resource_exhausted", "resource exhausted"))
        and not job_data.get(EDITORIAL_GLOBAL_CAPACITY_REPAIR_FIELD)
    ):
        return EDITORIAL_GLOBAL_CAPACITY_REPAIR_FIELD
    if (
        "editorial provider failed schema or quality review three times: editorial quality gate" in error_message
        and not job_data.get(EDITORIAL_TARGETED_QUALITY_REPAIR_FIELD)
    ):
        return EDITORIAL_TARGETED_QUALITY_REPAIR_FIELD
    if (
        "dramatic_structure." in error_message
        and "input should be a valid string" in error_message
        and not job_data.get(EDITORIAL_STRUCTURED_BEATS_REPAIR_FIELD)
    ):
        return EDITORIAL_STRUCTURED_BEATS_REPAIR_FIELD
    return None


def generation_deployment_repair_field(job_data: dict[str, Any]) -> str | None:
    editorial_repair = editorial_deployment_repair_field(job_data)
    if editorial_repair:
        return editorial_repair
    error_message = str((job_data.get("last_error") or {}).get("message") or "").lower()
    if (
        job_data.get("current_stage") == "scene_generation"
        and LEGACY_VEO_EMPTY_RESPONSE_ERROR in error_message
        and not job_data.get(VEO_EMPTY_RESPONSE_REPAIR_FIELD)
    ):
        return VEO_EMPTY_RESPONSE_REPAIR_FIELD
    if (
        job_data.get("current_stage") == "scene_generation"
        and ("high load" in error_message or "please try again later" in error_message)
        and not job_data.get(VEO_HIGH_LOAD_REPAIR_FIELD)
    ):
        return VEO_HIGH_LOAD_REPAIR_FIELD
    if (
        job_data.get("current_stage") == "scene_generation"
        and NATIVE_SPEECH_EDGE_GATE_ERROR in error_message
        and not job_data.get(NATIVE_SPEECH_EDGE_GATE_REPAIR_FIELD)
    ):
        return NATIVE_SPEECH_EDGE_GATE_REPAIR_FIELD
    if (
        job_data.get("current_stage") == "scene_generation"
        and NATIVE_SPEECH_EDGE_GATE_ERROR in error_message
        and not job_data.get(NATIVE_SPEECH_COMPLETION_REPAIR_FIELD)
    ):
        return NATIVE_SPEECH_COMPLETION_REPAIR_FIELD
    if (
        job_data.get("current_stage") == "render"
        and "sar " in error_message
        and "failed to configure output pad" in error_message
        and not job_data.get(RENDER_SAMPLE_ASPECT_RATIO_REPAIR_FIELD)
    ):
        return RENDER_SAMPLE_ASPECT_RATIO_REPAIR_FIELD
    return None


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
        self.speech_qa = SpeechQAProvider(settings)
        self.veo = VeoProvider(settings)
        self.tts = TextToSpeechProvider(settings)
        self.character_image = CharacterImageProvider(settings)
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

    def schedule_character_generation(self, character_id: str) -> None:
        task_key = f"character-generation:{character_id}"
        existing = self.tasks.get(task_key)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self.run_character_generation(character_id), name=task_key)
        self.tasks[task_key] = task
        task.add_done_callback(lambda _: self.tasks.pop(task_key, None))

    @staticmethod
    def _claim_generation_job(job_id: str) -> bool:
        """Atomically allow only one Cloud Run instance to execute a queued job."""
        with SessionLocal() as session:
            job = session.scalar(
                select(Resource)
                .where(Resource.id == job_id, Resource.kind == "generation_job")
                .with_for_update(skip_locked=True)
            )
            if not job:
                return False
            interrupted = job.status == "running" and bool(job.data.get("interrupted_at"))
            if job.status != "queued" and not interrupted:
                return False
            job.status = "running"
            job.data = {
                **job.data,
                "workflow_claimed_at": datetime.now(UTC).isoformat(),
                "workflow_claim_token": ResourceRepository.new_id("claim"),
                "interrupted_at": None,
            }
            session.add(job)
            session.commit()
            return True

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
        repaired_job_ids: list[str] = []
        with SessionLocal() as session:
            failed_jobs = list(
                session.scalars(
                    select(Resource).where(
                        Resource.kind == "generation_job",
                        Resource.status == "failed",
                    ).with_for_update(skip_locked=True)
                )
            )
            for failed_job in failed_jobs:
                repair_field = generation_deployment_repair_field(failed_job.data)
                if not repair_field:
                    continue
                current_stage = str(failed_job.data.get("current_stage") or "intake")
                retry_counts = dict(failed_job.data.get("automatic_stage_retries") or {})
                retry_counts[current_stage] = 0
                failed_job.status = "queued"
                failed_job.data = {
                    **failed_job.data,
                    **{
                        "automatic_stage_retries": retry_counts,
                        "last_error": None,
                        repair_field: datetime.now(UTC).isoformat(),
                        "retry_requested_at": datetime.now(UTC).isoformat(),
                        "retry_source": "deployment_repair",
                    },
                }
                session.add(failed_job)
                repaired_job_ids.append(failed_job.id)
            session.commit()
        for repaired_job_id in repaired_job_ids:
            logger.info("generation_deployment_repair_job_requeued job_id=%s", repaired_job_id)
            loop.call_later(RESUME_GRACE_SECONDS, self.schedule, repaired_job_id)
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
        with SessionLocal() as session:
            characters = list(
                session.scalars(
                    select(Resource).where(
                        Resource.kind == "character",
                        Resource.status.in_(["queued", "generating"]),
                    )
                )
            )
        for character in characters:
            loop.call_later(
                RESUME_GRACE_SECONDS,
                self.schedule_character_generation,
                character.id,
            )

    async def run_character_generation(self, character_id: str) -> None:
        with SessionLocal() as session:
            repo = ResourceRepository(session)
            character = repo.get_any(character_id, kind="character")
            if not character or character.status not in {"queued", "generating"}:
                return
            repo.update(character, status="generating", data={"started_at": datetime.now(UTC).isoformat()})
            try:
                output_base = (
                    self.settings.storage_root
                    / (character.project_id or "unknown")
                    / "characters"
                    / character.id
                )
                result = await self.character_image.generate(
                    str(
                        character.data.get("generation_prompt")
                        or character.data.get("description")
                        or character.data["name"]
                    ),
                    output_path=output_base,
                )
                demo_data = result is None
                if result is None:
                    # A valid deterministic PNG keeps local/CI explicit and never claims Gemini provenance.
                    output_path = output_base.with_suffix(".png")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(
                        base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                        )
                    )
                    mime_type = "image/png"
                else:
                    output_path, mime_type = result
                persisted = await asyncio.to_thread(
                    self.storage.persist,
                    output_path,
                    content_type=mime_type,
                )
                repo.update(
                    character,
                    status="ready",
                    data={
                        "local_path": persisted["local_path"],
                        "storage_uri": persisted["storage_uri"],
                        "reference_url": persisted["public_path"],
                        "mime_type": mime_type,
                        "provider": "deterministic_test_fixture" if demo_data else "google",
                        "model_id": (
                            "deterministic-test-fixture"
                            if demo_data
                            else self.settings.google_image_model
                        ),
                        "demo_data": demo_data,
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception as exc:
                logger.exception("character_generation_failed", extra={"character_id": character_id})
                repo.update(
                    character,
                    status="failed",
                    data={"error": str(exc), "failed_at": datetime.now(UTC).isoformat()},
                )
                refund_feature_charges(
                    session,
                    organization_id=character.organization_id,
                    reference_id=character.id,
                    reason="Character generation failed",
                )

    def _continuity_input(
        self,
        repo: ResourceRepository,
        *,
        scene: Resource,
        aspect_ratio: str,
        default_uri: str | None,
        default_mime_type: str | None,
    ) -> tuple[str | None, str | None, str]:
        storyboard_id = str(scene.data.get("storyboard_id") or "")
        position = int(scene.data.get("position") or 1)
        previous = next(
            (
                item
                for item in repo.list(
                    organization_id=scene.organization_id,
                    project_id=scene.project_id,
                    kind="scene",
                    limit=200,
                )
                if str(item.data.get("storyboard_id") or "") == storyboard_id
                and int(item.data.get("position") or 0) == position - 1
            ),
            None,
        )
        if previous:
            attempt_ids = dict(previous.data.get("latest_attempt_ids") or {})
            attempt_id = attempt_ids.get(aspect_ratio) or previous.data.get("latest_attempt_id")
            attempt = repo.get(
                str(attempt_id or ""),
                organization_id=scene.organization_id,
                project_id=scene.project_id,
                kind="scene_attempt",
            )
            if attempt and attempt.data.get("last_frame_storage_uri"):
                return (
                    str(attempt.data["last_frame_storage_uri"]),
                    str(attempt.data.get("last_frame_mime_type") or "image/jpeg"),
                    "previous_scene_last_frame",
                )
        if default_uri:
            return default_uri, default_mime_type or "image/jpeg", "character_reference"
        return None, None, "text_only"

    def _native_voice_reference_uri(
        self,
        repo: ResourceRepository,
        *,
        scene: Resource,
        aspect_ratio: str,
    ) -> str | None:
        """Use the first accepted scene on this character/narrator track as its voice anchor."""
        earlier = self._earlier_continuation_scenes(repo, scene=scene)
        reference_scene = earlier[0] if earlier else None
        if not reference_scene:
            return None
        attempt_ids = dict(reference_scene.data.get("latest_attempt_ids") or {})
        attempt_id = attempt_ids.get(aspect_ratio) or reference_scene.data.get("latest_attempt_id")
        reference_attempt = repo.get(
            str(attempt_id or ""),
            organization_id=scene.organization_id,
            project_id=scene.project_id,
            kind="scene_attempt",
        )
        if not reference_attempt or reference_attempt.status != "passed":
            return None
        return str(reference_attempt.data.get("storage_uri") or "") or None

    @staticmethod
    def _continuation_track(scene: Resource) -> str:
        explicit = str(scene.data.get("continuation_track") or scene.data.get("character_key") or "").strip()
        speaker = str(scene.data.get("speaker") or "").strip()
        speaker_kind = str(scene.data.get("speaker_kind") or "on_camera")
        raw = explicit or (speaker or "voice_over_narrator" if speaker_kind == "voice_over" else speaker) or "creator"
        return "_".join(part for part in "".join(char.lower() if char.isalnum() else " " for char in raw).split()) or "creator"

    def _earlier_continuation_scenes(
        self,
        repo: ResourceRepository,
        *,
        scene: Resource,
    ) -> list[Resource]:
        storyboard_id = str(scene.data.get("storyboard_id") or "")
        position = int(scene.data.get("position") or 0)
        track = self._continuation_track(scene)
        return sorted(
            [
                item
                for item in repo.list(
                    organization_id=scene.organization_id,
                    project_id=scene.project_id,
                    kind="scene",
                    limit=5000,
                )
                if str(item.data.get("storyboard_id") or "") == storyboard_id
                and int(item.data.get("position") or 0) < position
                and self._continuation_track(item) == track
            ],
            key=lambda item: int(item.data.get("position") or 0),
        )

    def _scene_extension_input_uri(
        self,
        repo: ResourceRepository,
        *,
        scene: Resource,
        aspect_ratio: str,
    ) -> str | None:
        """Return the rolling Veo context from the latest scene owned by the same role."""
        earlier = self._earlier_continuation_scenes(repo, scene=scene)
        previous = earlier[-1] if earlier else None
        if not previous:
            return None
        attempt_ids = dict(previous.data.get("latest_attempt_ids") or {})
        attempt_id = attempt_ids.get(aspect_ratio) or previous.data.get("latest_attempt_id")
        attempt = repo.get(
            str(attempt_id or ""),
            organization_id=scene.organization_id,
            project_id=scene.project_id,
            kind="scene_attempt",
        )
        if not attempt or attempt.status != "passed":
            return None
        return str(attempt.data.get("continuation_storage_uri") or "") or None

    async def _generate_scene_with_qa(
        self,
        *,
        session: Any,
        repo: ResourceRepository,
        job: Resource,
        scene: Resource,
        aspect_ratios: list[str],
        initial_attempt_number: int,
        native_audio: bool,
        default_reference_uri: str | None,
        default_reference_mime_type: str | None,
        regeneration_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str | None]]:
        use_live_video = self.settings.uses_live_video and not bool(job.data.get("test_mode"))
        max_automatic_retries = 2 if native_audio else 0
        attempt_number = initial_attempt_number
        voice_preset, locked_voice_profile = native_voice_profile(job.data.get("native_voice_preset"))
        veo_seed = int(job.data.get("veo_seed") or stable_veo_seed(job.id, voice_preset))
        continue_scenes = bool(
            job.data.get("continue_scenes")
            if job.data.get("continue_scenes") is not None
            else native_audio and job.data.get("visual_mode") == "ugc_creator"
        )
        voice_locked_continuation = bool(continue_scenes and native_audio)
        continuation_track = self._continuation_track(scene)
        scene_voice_profile = str(scene.data.get("voice_direction") or locked_voice_profile)
        for automatic_retry in range(max_automatic_retries + 1):
            prompt = str(scene.data.get("visual_prompt") or "").strip()
            if not prompt:
                raise RuntimeError(f"Director returned no visual prompt for {scene.id}")
            attempt_items: list[dict[str, Any]] = []
            latest_attempt_ids: dict[str, str] = {}
            output_uris: dict[str, str | None] = {}
            speech_passed = True
            voice_passed = True
            speech_needs_compression = False
            speech_prompt_corrections: list[str] = []
            for aspect_ratio in aspect_ratios:
                ratio_slug = aspect_ratio.replace(":", "x")
                suffix = f"_attempt_{attempt_number}" if attempt_number > 1 else ""
                output_path = (
                    self.settings.storage_root
                    / (job.project_id or "unknown")
                    / job.id
                    / "scenes"
                    / f"{scene.id}{suffix}_{ratio_slug}.mp4"
                )
                extension_video_uri = (
                    self._scene_extension_input_uri(repo, scene=scene, aspect_ratio=aspect_ratio)
                    if continue_scenes
                    else None
                )
                earlier_track_scenes = self._earlier_continuation_scenes(repo, scene=scene) if continue_scenes else []
                if continue_scenes and earlier_track_scenes and not extension_video_uri:
                    raise RuntimeError(
                        f"Previous Veo context for continuation track {continuation_track} is missing "
                        f"for {scene.id} ({aspect_ratio})"
                    )
                if extension_video_uri:
                    input_uri, input_mime_type, input_kind = (
                        extension_video_uri,
                        "video/mp4",
                        f"continuation_track:{continuation_track}",
                    )
                elif continue_scenes:
                    root_reference_uri = (
                        default_reference_uri if job.data.get("visual_mode") == "ugc_creator" else None
                    )
                    input_uri, input_mime_type, input_kind = (
                        root_reference_uri,
                        (default_reference_mime_type or "image/jpeg") if root_reference_uri else None,
                        f"continuation_track_root:{continuation_track}",
                    )
                elif job.data.get("visual_mode") in {"storytelling", "cinematic", "motion_graphics"}:
                    input_uri, input_mime_type, input_kind = None, None, "independent_scene_vignette"
                else:
                    input_uri, input_mime_type, input_kind = self._continuity_input(
                        repo,
                        scene=scene,
                        aspect_ratio=aspect_ratio,
                        default_uri=default_reference_uri,
                        default_mime_type=default_reference_mime_type,
                    )
                continuation_output_path = (
                    output_path.with_name(f"{output_path.stem}_continuation.mp4")
                    if continue_scenes
                    else None
                )
                scene_started = time.perf_counter()
                if use_live_video:
                    generated = await self.veo.generate_scene(
                        prompt,
                        aspect_ratio=aspect_ratio,
                        output_path=output_path,
                        generate_audio=native_audio,
                        reference_image_uri=input_uri,
                        reference_image_mime_type=input_mime_type,
                        duration_seconds=float(scene.data.get("duration_target") or 8),
                        seed=veo_seed,
                        extension_video_uri=extension_video_uri,
                        continuation_output_path=continuation_output_path,
                    )
                    if generated is None:
                        raise RuntimeError(f"Live Veo returned no output for {scene.id} ({aspect_ratio})")
                else:
                    generated = await asyncio.to_thread(
                        render_scene_fixture,
                        label=f"Scene {scene.data.get('position') or scene.id}",
                        aspect_ratio=aspect_ratio,
                        output_path=output_path,
                        duration_seconds=min(2.0, float(scene.data.get("duration_target") or 2)),
                    )
                persisted = await asyncio.to_thread(self.storage.persist, generated, content_type="video/mp4")
                continuation_generated = (
                    continuation_output_path
                    if continuation_output_path and continuation_output_path.exists()
                    else generated
                )
                continuation_conditioning = continuation_generated
                if continue_scenes:
                    conditioning_path = output_path.with_name(f"{output_path.stem}_conditioning.mp4")
                    continuation_conditioning = await asyncio.to_thread(
                        prepare_veo_extension_input,
                        continuation_generated,
                        conditioning_path,
                    )
                persisted_continuation = (
                    await asyncio.to_thread(self.storage.persist, continuation_conditioning, content_type="video/mp4")
                    if continue_scenes
                    else None
                )
                last_frame_path = output_path.with_name(f"{output_path.stem}_last.jpg")
                await asyncio.to_thread(extract_last_frame, generated, last_frame_path)
                persisted_last_frame = await asyncio.to_thread(
                    self.storage.persist,
                    last_frame_path,
                    content_type="image/jpeg",
                )
                if native_audio and not job.data.get("test_mode"):
                    try:
                        speech_qa = await self.speech_qa.analyze(
                            video_uri=persisted["storage_uri"],
                            expected_text=str(scene.data.get("narration") or ""),
                            duration_target=float(scene.data.get("duration_target") or 8),
                            require_immediate_hook=int(scene.data.get("position") or 0) == 1,
                            require_voice_at_end=bool(
                                scene.data.get("continuous_extension_has_next")
                            ),
                        )
                    except TypeError as exc:
                        if "unexpected keyword" not in str(exc):
                            raise
                        # Compatibility for injected test/evaluation adapters using the pre-v5 interface.
                        speech_qa = await self.speech_qa.analyze(
                            video_uri=persisted["storage_uri"],
                            expected_text=str(scene.data.get("narration") or ""),
                            duration_target=float(scene.data.get("duration_target") or 8),
                        )
                    if voice_locked_continuation:
                        voice_reference_uri = self._native_voice_reference_uri(
                            repo,
                            scene=scene,
                            aspect_ratio=aspect_ratio,
                        )
                        voice_qa = await self.speech_qa.compare_voice(
                            reference_video_uri=voice_reference_uri,
                            candidate_video_uri=persisted["storage_uri"],
                            voice_profile=scene_voice_profile,
                        )
                        voice_qa["generation_strategy"] = (
                            "character_track_extension" if extension_video_uri else "continuation_track_root"
                        )
                    else:
                        voice_reference_uri = None
                        voice_qa = {
                            "passed": True,
                            "same_speaker": None,
                            "similarity": None,
                            "issues": [],
                            "mode": "intentional_scene_local_voice",
                            "provider": "internal",
                            "generation_strategy": "independent_scene_vignette",
                        }
                else:
                    timing = dict(scene.data.get("speech_timing") or {})
                    speech_qa = {
                        "passed": bool(
                            not timing
                            or float(timing.get("estimated_seconds") or 0)
                            <= float(scene.data.get("duration_target") or 8)
                        ),
                        "mode": "preflight_timing",
                        "transcript": None,
                        "coverage": None,
                        "issues": [],
                        "provider": "internal",
                        "demo_data": not use_live_video,
                    }
                    voice_reference_uri = None
                    voice_qa = {
                        "passed": True,
                        "same_speaker": True,
                        "similarity": 1.0,
                        "issues": [],
                        "mode": "not_applicable",
                        "provider": "internal",
                        "demo_data": not use_live_video,
                    }
                speech_passed = speech_passed and bool(speech_qa.get("passed"))
                voice_passed = voice_passed and bool(voice_qa.get("passed"))
                if not speech_qa.get("passed"):
                    speech_needs_compression = speech_needs_compression or bool(
                        float(speech_qa.get("coverage") or 0) < 0.82
                        or not speech_qa.get("last_phrase_complete", True)
                        or "edit point" in " ".join(speech_qa.get("issues") or []).lower()
                    )
                    issue_text = " ".join(speech_qa.get("issues") or []).lower()
                    if "starts too late" in issue_text:
                        speech_prompt_corrections.append(
                            "HOOK TIMING CORRECTION: open on the first spoken word at time zero; no breath, silence, reaction or lead-in."
                        )
                    logger.warning(
                        "scene_speech_qa_rejected job_id=%s scene_id=%s attempt=%s coverage=%s "
                        "speech_start_seconds=%s speech_end_seconds=%s last_phrase_complete=%s issues=%s",
                        job.id,
                        scene.id,
                        attempt_number,
                        speech_qa.get("coverage"),
                        speech_qa.get("speech_start_seconds"),
                        speech_qa.get("speech_end_seconds"),
                        speech_qa.get("last_phrase_complete"),
                        speech_qa.get("issues"),
                    )
                if use_live_video:
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
                            "speech_qa_passed": speech_qa.get("passed"),
                            "voice_qa_passed": voice_qa.get("passed"),
                        },
                    )
                attempt_passed = bool(speech_qa.get("passed") and voice_qa.get("passed"))
                attempt = repo.add(
                    kind="scene_attempt",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status=(
                        "passed"
                        if attempt_passed
                        else "speech_qa_failed"
                        if not speech_qa.get("passed")
                        else "voice_qa_failed"
                    ),
                    data={
                        "generation_job_id": job.id,
                        "scene_id": scene.id,
                        "attempt": attempt_number,
                        "automatic_retry": automatic_retry,
                        "aspect_ratio": aspect_ratio,
                        "model_id": self.settings.veo_model if use_live_video else "deterministic-test-fixture",
                        "prompt_version": "editorial-director-v7-pro-quality-gate",
                        "visual_prompt": prompt,
                        "narration": scene.data.get("narration"),
                        "output_uri": str(generated),
                        "storage_uri": persisted["storage_uri"],
                        "public_path": persisted["public_path"],
                        "continuation_output_uri": str(continuation_generated) if continue_scenes else None,
                        "continuation_conditioning_uri": str(continuation_conditioning) if continue_scenes else None,
                        "continuation_storage_uri": (
                            persisted_continuation["storage_uri"] if persisted_continuation else None
                        ),
                        "continuation_public_path": (
                            persisted_continuation["public_path"] if persisted_continuation else None
                        ),
                        "last_frame_storage_uri": persisted_last_frame["storage_uri"],
                        "last_frame_public_path": persisted_last_frame["public_path"],
                        "last_frame_mime_type": "image/jpeg",
                        "continuity_input_uri": input_uri,
                        "continuity_input_kind": input_kind,
                        "generation_strategy": (
                            "character_track_extension"
                            if extension_video_uri
                            else "continuation_track_root"
                            if continue_scenes
                            else "independent_scene_vignette"
                        ),
                        "speech_qa": speech_qa,
                        "voice_qa": voice_qa,
                        "voice_reference_uri": voice_reference_uri,
                        "native_voice_preset": voice_preset,
                        "native_voice_profile": locked_voice_profile,
                        "scene_voice_profile": scene_voice_profile,
                        "continuation_track": continuation_track,
                        "veo_seed": veo_seed,
                        "qa_status": "passed" if attempt_passed else "failed",
                        "demo_data": not use_live_video,
                        "audio_mode": "veo_native" if native_audio else "google_tts",
                        "character_id": job.data.get("character_id"),
                        "regeneration_id": regeneration_id,
                        "billable_seconds": (
                            (7 if extension_video_uri else veo_request_duration(float(scene.data.get("duration_target") or 8)))
                            if use_live_video
                            else 0
                        ),
                        "cost_usd": None,
                    },
                )
                latest_attempt_ids[aspect_ratio] = attempt.id
                output_uris[aspect_ratio] = str(generated)
                attempt_items.append(
                    {
                        "scene_id": scene.id,
                        "attempt_id": attempt.id,
                        "attempt": attempt_number,
                        "aspect_ratio": aspect_ratio,
                        "model_id": attempt.data["model_id"],
                        "demo_data": attempt.data["demo_data"],
                        "output_uri": str(generated),
                        "storage_uri": persisted["storage_uri"],
                        "public_path": persisted["public_path"],
                        "continuation_output_uri": str(continuation_generated) if continue_scenes else None,
                        "continuation_conditioning_uri": str(continuation_conditioning) if continue_scenes else None,
                        "continuation_storage_uri": (
                            persisted_continuation["storage_uri"] if persisted_continuation else None
                        ),
                        "speech_qa": speech_qa,
                        "voice_qa": voice_qa,
                        "voice_reference_uri": voice_reference_uri,
                        "native_voice_preset": voice_preset,
                        "veo_seed": veo_seed,
                        "continuity_input_kind": input_kind,
                        "generation_strategy": (
                            "character_track_extension"
                            if extension_video_uri
                            else "continuation_track_root"
                            if continue_scenes
                            else "independent_scene_vignette"
                        ),
                        "continuation_track": continuation_track,
                        "last_frame_storage_uri": persisted_last_frame["storage_uri"],
                        "billable_seconds": attempt.data["billable_seconds"],
                    }
                )
            if speech_passed and voice_passed:
                return attempt_items, latest_attempt_ids, output_uris
            if automatic_retry >= max_automatic_retries:
                failed_checks = " and ".join(
                    label
                    for label, passed in (("speech", speech_passed), ("voice identity", voice_passed))
                    if not passed
                )
                raise RuntimeError(
                    f"Native audio {failed_checks} QA failed for {scene.id} "
                    f"after {max_automatic_retries + 1} attempts"
                )
            if not speech_passed and speech_needs_compression:
                fitted = await self.editorial.fit_dialogue(
                    [dict(scene.data)],
                    native_audio=True,
                    native_voice_profile=locked_voice_profile,
                    compression=max(0.55, 0.78 - automatic_retry * 0.12),
                )
                updated_scene = fitted[0]
            else:
                updated_scene = dict(scene.data)
            retry_prompt = str(updated_scene.get("visual_prompt") or "").strip()
            if speech_prompt_corrections:
                retry_prompt = f"{retry_prompt} {' '.join(dict.fromkeys(speech_prompt_corrections))}"
            if not voice_passed:
                retry_prompt = (
                    f"{retry_prompt} VOICE IDENTITY CORRECTION: The previous take was rejected because the "
                    f"speaker changed. Cast exactly this role-specific voice: {scene_voice_profile}. Keep the same "
                    f"speaker identity as the first accepted scene on continuation track {continuation_track}; "
                    "do not borrow a voice from another character or narrator track."
                )
            repo.update(
                scene,
                status="regenerating",
                data={
                    "narration": updated_scene.get("narration"),
                    "visual_prompt": retry_prompt,
                    "visual_prompt_base": updated_scene.get("visual_prompt_base"),
                    "speech_timing": updated_scene.get("speech_timing"),
                    "automatic_speech_retries": (
                        automatic_retry + 1
                        if not speech_passed
                        else scene.data.get("automatic_speech_retries", 0)
                    ),
                    "automatic_voice_retries": (
                        automatic_retry + 1
                        if not voice_passed
                        else scene.data.get("automatic_voice_retries", 0)
                    ),
                },
            )
            attempt_number += 1
        raise RuntimeError(f"Scene generation did not produce a passing attempt for {scene.id}")

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
                repo.update(scene, status="regenerating", data={"visual_prompt": prompt})
                repo.update(regeneration, status="running", data={"started_at": datetime.now(UTC).isoformat()})
                native_audio = job.data.get("audio_mode") == "veo_native"
                cascade_scenes = [scene]
                if job.data.get("continue_scenes"):
                    selected_track = self._continuation_track(scene)
                    cascade_scenes = sorted(
                        [
                            item
                            for item in repo.list(
                                organization_id=job.organization_id,
                                project_id=job.project_id,
                                kind="scene",
                                limit=5000,
                            )
                            if str(item.data.get("storyboard_id") or "") == storyboard.id
                            and int(item.data.get("position") or 0) >= int(scene.data.get("position") or 0)
                            and self._continuation_track(item) == selected_track
                        ],
                        key=lambda item: int(item.data.get("position") or 0),
                    )
                affected_scene_ids = {item.id for item in cascade_scenes}
                for cascade_index, target_scene in enumerate(cascade_scenes):
                    target_attempt = int(target_scene.data.get("attempt", 0)) + 1
                    generated, generated_ids, generated_uris = await self._generate_scene_with_qa(
                        session=session,
                        repo=repo,
                        job=job,
                        scene=target_scene,
                        aspect_ratios=aspect_ratios,
                        initial_attempt_number=target_attempt,
                        native_audio=native_audio,
                        default_reference_uri=job.data.get("reference_image_uri"),
                        default_reference_mime_type=job.data.get("reference_image_mime_type"),
                        regeneration_id=regeneration.id,
                    )
                    resolved_attempt = max(int(item.get("attempt") or target_attempt) for item in generated)
                    repo.update(
                        target_scene,
                        status="generated",
                        data={
                            "attempt": resolved_attempt,
                            "latest_attempt_id": generated_ids.get(aspect_ratios[0]),
                            "latest_attempt_ids": generated_ids,
                            "output_uri": generated_uris.get(aspect_ratios[0]),
                            "output_uris": generated_uris,
                            "cascade_regeneration_id": regeneration.id if cascade_index else None,
                        },
                    )
                    replacement_attempts.extend(generated)
                    if cascade_index == 0:
                        latest_attempt_ids = generated_ids
                        output_uris = generated_uris
                        attempt_number = resolved_attempt

                generation_output = self._completed_stage_output(job, "scene_generation")
                retained_attempts = [
                    item
                    for item in list(generation_output.get("attempts") or [])
                    if item.get("scene_id") not in affected_scene_ids
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
                    },
                )
                storyboard_scenes = [dict(item) for item in storyboard.data.get("scenes", [])]
                cascade_by_position = {
                    int(item.data.get("position") or 0): dict(item.data) for item in cascade_scenes
                }
                for index, item in enumerate(storyboard_scenes):
                    position = int(item.get("position") or 0)
                    if position in cascade_by_position:
                        storyboard_scenes[index] = cascade_by_position[position]
                repo.update(storyboard, data={"scenes": storyboard_scenes})
                script_stage = self._completed_stage_output(job, "script")
                script = repo.get_any(str(script_stage.get("script_id") or ""), kind="script")
                if script:
                    script_payload = dict(script.data.get("script") or {})
                    script_payload.update(
                        {
                            "beats": storyboard_scenes,
                            "voiceover": " ".join(
                                str(item.get("narration") or "").strip() for item in storyboard_scenes
                            ).strip(),
                        }
                    )
                    repo.update(script, data={"script": script_payload})
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
                refund_feature_charges(
                    session,
                    organization_id=regeneration.organization_id,
                    reference_id=regeneration.id,
                    reason="Scene regeneration failed",
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

    async def _complete_automatic_publications(
        self,
        session: Any,
        repo: ResourceRepository,
        job: Resource,
        version_ids: list[str],
        *,
        title: str,
    ) -> None:
        """Approve an automated render and hand it to every connected channel.

        Selecting the final automation mode is the workspace owner's explicit
        instruction to publish every completed render to every connected channel.
        """
        if not job.data.get("automatic_publish") or not version_ids:
            return

        connections = repo.list(
            organization_id=job.organization_id,
            project_id=str(job.project_id),
            kind="connection",
            statuses={"active", "healthy"},
            limit=200,
        )
        connections = [
            connection
            for connection in connections
            if str(connection.data.get("provider") or "") in {"youtube", "instagram", "tiktok"}
        ]
        if not connections:
            repo.update(
                job,
                data={
                    "automatic_publication_status": "no_connected_channels",
                    "automatic_publication_ids": [],
                },
            )
            return

        # Import route-level orchestration lazily to reuse the same validation,
        # provider policy and upload code as an interactive publication.
        from .routes import _review_video_version, confirm_publication, prepare_publication
        from .schemas import PublicationConfirm, PublicationCreate, ReviewAction
        from .security import ALL_SCOPES, Principal

        principal = Principal(
            actor_id="automation_scheduler",
            organization_id=job.organization_id,
            project_id=str(job.project_id),
            role="owner",
            scopes=ALL_SCOPES,
            project_scope=frozenset({str(job.project_id)}),
        )
        version_id = version_ids[0]
        version = repo.get_any(version_id, kind="video_version")
        if not version:
            return
        if version.status != "approved":
            _review_video_version(
                version_id=version_id,
                review_status="approved",
                payload=ReviewAction(comment="Approved by configured publication automation"),
                principal=principal,
                session=session,
            )

        project = repo.get_any(str(job.project_id), kind="project")
        context = dict((project.data if project else {}).get("context") or {})
        raw_keywords: list[str] = []
        for key in ("product_keywords", "problem_keywords", "audience_interest_keywords"):
            raw_keywords.extend(str(item) for item in context.get(key) or [])
        hashtags = [
            "".join(character for character in keyword if character.isalnum() or character == "_")[:50]
            for keyword in raw_keywords
        ]
        hashtags = [item for item in hashtags if item][:8]
        caption = str(job.data.get("publication_caption") or title)
        publication_ids: list[str] = []
        errors: list[dict[str, str]] = []
        for connection in connections:
            platform = str(connection.data.get("provider"))
            existing = [
                item
                for item in repo.list(
                    organization_id=job.organization_id,
                    project_id=str(job.project_id),
                    kind="publication",
                    limit=200,
                )
                if item.data.get("video_version_id") == version_id
                and item.data.get("connection_id") == connection.id
            ]
            if existing:
                publication_ids.append(existing[0].id)
                continue
            try:
                payload = PublicationCreate(
                    video_version_id=version_id,
                    connection_id=connection.id,
                    platform=platform,
                    title=title,
                    caption=caption,
                    hashtags=hashtags,
                    privacy=(
                        "public"
                        if platform in {"youtube", "instagram"}
                        else "SELF_ONLY"
                    ),
                    creator_info_acknowledged=platform == "tiktok",
                    allow_comments=True if platform == "tiktok" else None,
                    allow_duet=False if platform == "tiktok" else None,
                    allow_stitch=False if platform == "tiktok" else None,
                    synthetic_media_disclosure=True,
                )
                prepared = prepare_publication(
                    payload=payload,
                    idempotency_key=f"automatic-publication:{job.id}:{connection.id}",
                    principal=principal,
                    session=session,
                    settings=self.settings,
                )
                publication_id = str(prepared["publication_id"])
                publication_ids.append(publication_id)
                publication = repo.get_any(publication_id, kind="publication")
                if publication:
                    repo.update(
                        publication,
                        data={
                            "automatic": True,
                            "automation_consent_granted_at": datetime.now(UTC).isoformat(),
                        },
                    )
                await confirm_publication(
                    publication_id=publication_id,
                    payload=PublicationConfirm(
                        confirmation_token=str(prepared["confirmation_token"]),
                        explicit_consent=bool(prepared.get("requires_user_consent")),
                    ),
                    principal=principal,
                    session=session,
                    settings=self.settings,
                )
            except Exception as exc:  # A provider failure must not discard the completed video.
                logger.exception(
                    "automatic_publication_failed job_id=%s connection_id=%s",
                    job.id,
                    connection.id,
                )
                errors.append({"connection_id": connection.id, "platform": platform, "message": str(exc)})

        repo.update(
            job,
            data={
                "automatic_publication_status": "attention_required" if errors else "published",
                "automatic_publication_ids": publication_ids,
                "automatic_publication_consent_required_ids": [],
                "automatic_publication_errors": errors,
            },
        )

    async def run(self, job_id: str) -> None:
        if not self._claim_generation_job(job_id):
            logger.info("generation_job_claim_skipped job_id=%s", job_id)
            return
        with SessionLocal() as session:
            repo = ResourceRepository(session)
            job = repo.get_any(job_id, kind="generation_job")
            if not job or job.status in {"ready", "cancelled", "blocked", "failed"}:
                return
            await self._emit(session, job, "generation.started")
            while True:
                try:
                    await self._run_pipeline(session, repo, job)
                    return
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
                    current_stage = str(job.data.get("current_stage") or "intake")
                    logger.exception(
                        "generation_stage_failed job_id=%s stage=%s",
                        job_id,
                        current_stage,
                    )
                    retry_counts = dict(job.data.get("automatic_stage_retries") or {})
                    retry_count = int(retry_counts.get(current_stage, 0))
                    if retryable_generation_error(exc) and retry_count < MAX_AUTOMATIC_STAGE_RETRIES:
                        retry_delay = generation_retry_delay_seconds(exc, retry_count)
                        self._set_stage(repo, job, current_stage, "failed", error=str(exc))
                        retry_counts[current_stage] = retry_count + 1
                        repo.update(
                            job,
                            status="queued",
                            data={
                                "automatic_stage_retries": retry_counts,
                                "last_error": {
                                    "code": "automatic_retry_scheduled",
                                    "message": str(exc),
                                    "retryable": True,
                                    "stage": current_stage,
                                },
                                "retry_requested_at": datetime.now(UTC).isoformat(),
                                "retry_after_seconds": retry_delay,
                            },
                        )
                        await self._emit(
                            session,
                            job,
                            "generation.retry_scheduled",
                            {
                                "stage": current_stage,
                                "attempt": retry_count + 1,
                                "retry_after_seconds": retry_delay,
                                "error": str(exc),
                            },
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.exception("generation_failed", extra={"job_id": job_id})
                    self._set_stage(repo, job, current_stage, "failed", error=str(exc))
                    repo.update(
                        job,
                        status="failed",
                        data={
                            "last_error": {
                                "code": "generation_failed",
                                "message": str(exc),
                                "retryable": True,
                                "stage": current_stage,
                            },
                            "failed_at": datetime.now(UTC).isoformat(),
                        },
                    )
                    refund_feature_charges(
                        session,
                        organization_id=job.organization_id,
                        reference_id=job.id,
                        reason="Generation failed before a usable video was produced",
                    )
                    await self._emit(session, job, "generation.failed", {"stage": current_stage, "error": str(exc)})
                    return

    async def _run_pipeline(self, session: Any, repo: ResourceRepository, job: Resource) -> None:
        stages = {item.get("name"): item for item in job.data.get("stages", [])}
        render_stage = stages.get("render", {})
        voice_stage = stages.get("voice_audio", {})
        scene_stage = stages.get("scene_generation", {})
        storyboard_stage = stages.get("storyboard", {})
        intake_stage = stages.get("intake", {})
        research_stage = stages.get("research", {})
        editorial_stage = stages.get("editorial_strategy", {})
        script_stage = stages.get("script", {})
        policy_stage = stages.get("fact_policy", {})
        if render_stage.get("status") in {"running", "failed"} and voice_stage.get("status") == "completed":
            await self._resume_from_render(session, repo, job)
            return
        if (
            storyboard_stage.get("output")
            and scene_stage.get("status") in {"pending", "running", "failed", "completed"}
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
        supported_visual_modes = {
            "ugc_creator",
            "ugc_native_audio",
            "storytelling",
            "cinematic",
            "motion_graphics",
        }
        visual_mode = str(
            job.data.get("visual_mode")
            or (input_resource.data.get("visual_mode") if input_resource else None)
            or "ugc_creator"
        )
        legacy_native_audio = visual_mode == "ugc_native_audio"
        if legacy_native_audio:
            visual_mode = "ugc_creator"
        if visual_mode == "product_demo":
            visual_mode = "storytelling"
        if visual_mode not in supported_visual_modes:
            raise RuntimeError(f"Unsupported visual mode: {visual_mode}")
        aspect_ratios = list(job.data.get("aspect_ratios") or ["9:16"])
        character_id = job.data.get("character_id") or (input_resource.data.get("character_id") if input_resource else None)
        character = repo.get_any(str(character_id), kind="character") if character_id else None
        if character_id and (
            not character
            or character.organization_id != job.organization_id
            or character.project_id != job.project_id
            or character.status != "ready"
        ):
            raise RuntimeError("Selected reusable character is missing or not ready")
        character_profile = (
            f"Selected reusable creator named {character.data.get('name')}: {character.data.get('description')}"
            if character
            else ""
        )
        reference_image_uri = str(character.data.get("storage_uri") or "") if character else ""
        reference_image_mime_type = str(character.data.get("mime_type") or "image/jpeg") if character else None
        audio_mode = str(
            job.data.get("audio_mode")
            or (input_resource.data.get("audio_mode") if input_resource else None)
            or ("veo_native" if legacy_native_audio else "google_tts")
        )
        if audio_mode not in {"google_tts", "veo_native"}:
            raise RuntimeError(f"Unsupported audio mode: {audio_mode}")
        native_audio = audio_mode == "veo_native"
        continue_scenes = bool(
            job.data.get("continue_scenes")
            if job.data.get("continue_scenes") is not None
            else native_audio and visual_mode == "ugc_creator"
        )
        voice_preset, locked_voice_profile = native_voice_profile(
            job.data.get("native_voice_preset")
            or (input_resource.data.get("native_voice_preset") if input_resource else None)
        )
        veo_seed = int(job.data.get("veo_seed") or stable_veo_seed(job.id, voice_preset))

        repo.update(
            job,
            data={
                "visual_mode": visual_mode,
                "audio_mode": audio_mode,
                "continue_scenes": continue_scenes,
                "character_id": character.id if character else None,
                "character_profile": character_profile or None,
                "reference_image_uri": reference_image_uri or None,
                "reference_image_mime_type": reference_image_mime_type,
                "native_voice_preset": voice_preset,
                "native_voice_profile": locked_voice_profile if native_audio else None,
                "veo_seed": veo_seed,
            },
        )
        if intake_stage.get("status") != "completed":
            self._set_stage(repo, job, "intake", "running")
            if project.data.get("autopilot_paused") and job.data.get("automatic", False):
                self._set_stage(repo, job, "intake", "blocked", error="Project autopilot is paused")
                raise RuntimeError("Project autopilot is paused")
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
                        "audio_mode": audio_mode,
                        "continue_scenes": continue_scenes,
                        "native_voice_preset": voice_preset,
                        "native_voice_profile": locked_voice_profile if native_audio else None,
                        "veo_seed": veo_seed,
                        "character_id": character.id if character else None,
                    }
                },
            )

        if research_stage.get("status") == "completed" and research_stage.get("output"):
            research_output = dict(research_stage["output"])
            research_run = repo.get_any(str(research_output.get("research_run_id") or ""), kind="research_run")
            candidate = repo.get_any(str(research_output.get("candidate_id") or ""), kind="topic_candidate")
            if not research_run or not candidate:
                raise RuntimeError("Cannot resume: persisted research checkpoint is missing")
            packet = ResearchPacket(
                request_id=str(
                    research_output.get("parallel_request_id")
                    or (research_run.data.get("parallel_request_ids") or ["persisted"])[0]
                ),
                objective=str(research_run.data.get("objective") or ""),
                sources=list(research_run.data.get("sources") or []),
                claims=list(research_run.data.get("claims") or []),
                raw=dict(research_run.data.get("parallel_result_metadata") or {}),
            )
            opportunity = topic_score(len(packet.sources))
        else:
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
                    "candidate_type": "problem_solution",
                    "target_audience_insight": audience,
                    "content_goal": objective,
                    "core_message": title,
                    "problem_or_tension": f"{audience} needs a concrete, credible way to act on this topic.",
                    "proposed_solution": f"Explain {title} through one observable human situation and a supported action.",
                    "informational_value": "A researched explanation with one directly useful example.",
                    "entertainment_hook": "A recognizable before-and-after contrast.",
                    "virality_mechanism": "Fast recognition, specific payoff and shareable practical value.",
                    "creative_direction": "Turn the core claim into physical action in a believable real-world location.",
                    "suitable_visual_modes": [visual_mode],
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

        persisted_package = (editorial_stage.get("output") or {}).get("package")
        if editorial_stage.get("status") == "completed" and isinstance(persisted_package, dict):
            package = dict(persisted_package)
            package_scenes = list((package.get("storyboard") or {}).get("scenes") or [])
        else:
            self._set_stage(repo, job, "editorial_strategy", "running")
            editorial_started = time.perf_counter()
            review_history: list[dict[str, Any]] = []
            revision_feedback = str(job.data.get("script_revision_feedback") or "").strip()
            assessment: dict[str, Any] = {"approved": False, "issues": ["Review did not run"]}
            package = {}
            package_scenes = []
            for quality_attempt in range(1, 4):
                package = await self.editorial.create_package(
                    title=title,
                    audience=audience,
                    objective=objective,
                    brand=brand,
                    evidence=packet,
                    duration_seconds=int(job.data.get("target_duration_seconds", 30)),
                    visual_mode=visual_mode,
                    native_audio=native_audio,
                    continue_scenes=continue_scenes,
                    native_voice_profile=locked_voice_profile,
                    aspect_ratios=aspect_ratios,
                    requested_hook=requested_hook,
                    content_format=content_format,
                    creative_context={
                        **dict(candidate.data),
                        **(dict(input_resource.data) if input_resource else {}),
                        "script_revision_feedback": revision_feedback or None,
                        "whole_script_review_attempt": quality_attempt,
                    },
                    character_profile=character_profile,
                    scene_count_min=int(job.data.get("scene_count_min", 4)),
                    scene_count_max=int(job.data.get("scene_count_max", 6)),
                    scene_count_flex=int(job.data.get("scene_count_flex", 2)),
                )
                package_scenes = list((package.get("storyboard") or {}).get("scenes") or [])
                await self.editorial.fit_dialogue(
                    package_scenes,
                    native_audio=native_audio,
                    native_voice_profile=locked_voice_profile,
                )
                if package.get("storyboard") is not None:
                    package["storyboard"]["scenes"] = package_scenes
                if package.get("script") is not None:
                    package["script"]["beats"] = package_scenes
                    package["script"]["voiceover"] = " ".join(
                        str(scene.get("narration") or "").strip() for scene in package_scenes
                    ).strip()
                assessment = await self.editorial.review_package(
                    package,
                    brand=brand,
                    title=title,
                    audience=audience,
                    objective=objective,
                )
                review_history.append({"attempt": quality_attempt, **assessment})
                if assessment.get("approved"):
                    break
                revision_feedback = str(
                    assessment.get("regeneration_feedback")
                    or "; ".join(str(item) for item in assessment.get("issues") or [])
                ).strip()
            package["script_quality_review"] = {
                "approved": bool(assessment.get("approved")),
                "attempts": review_history,
                "final_feedback": revision_feedback or None,
                "reviewed_with": self.settings.gemini_editorial_model if self.settings.uses_live_research else "mock-gemini",
            }
            if not assessment.get("approved"):
                # Never spend on Veo after three rejected scripts. The authored package remains
                # available in the existing review UI and can use the same comment retry flow.
                repo.update(
                    job,
                    data={
                        "generation_start_mode": "review_script",
                        "script_quality_review_required": True,
                        "script_revision_feedback": revision_feedback,
                    },
                )
            await self._emit(
                session,
                job,
                "model.call.completed",
                {
                    "stage": "editorial_strategy",
                    "provider": "google",
                    "model": self.settings.gemini_editorial_model if self.settings.uses_live_research else "mock-gemini",
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
                    "scene_count": len(package_scenes),
                    "script_quality_review": package.get("script_quality_review"),
                    "requested_scene_range": {
                        "min": int(job.data.get("scene_count_min", 4)),
                        "max": int(job.data.get("scene_count_max", 6)),
                        "flex": int(job.data.get("scene_count_flex", 2)),
                    },
                    "package": package,
                },
            )
        concepts = package.get("concepts") or []

        if script_stage.get("status") == "completed" and script_stage.get("output"):
            script = repo.get_any(str(script_stage["output"].get("script_id") or ""), kind="script")
            if not script:
                raise RuntimeError("Cannot resume: persisted script checkpoint is missing")
        else:
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

        if policy_stage.get("status") == "completed" and isinstance(policy_stage.get("output"), dict):
            policy = dict(policy_stage["output"])
        else:
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
                    resource_id=f"{job.id}_{storyboard.id}_scene_{index + 1}",
                    kind="scene",
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    status="planned",
                    data=scene_data,
                )
            )
        self._set_stage(repo, job, "storyboard", "completed", output={"storyboard_id": storyboard.id, "scene_ids": [item.id for item in scene_resources]})

        if (
            job.data.get("generation_start_mode") == "review_script"
            and not job.data.get("script_approved_at")
        ):
            repo.update(
                job,
                status="awaiting_script_review",
                data={
                    "current_stage": "script_review",
                    "progress": 6 / len(STAGES),
                    "script_id": script.id,
                    "storyboard_id": storyboard.id,
                    "scene_ids": [item.id for item in scene_resources],
                    "script_review_requested_at": datetime.now(UTC).isoformat(),
                },
            )
            await self._emit(
                session,
                job,
                "script.review_requested",
                {"script_id": script.id, "storyboard_id": storyboard.id},
            )
            return

        self._set_stage(repo, job, "scene_generation", "running")
        scene_attempts: list[dict[str, Any]] = []
        for scene in scene_resources:
            attempts, latest_attempt_ids, output_uris = await self._generate_scene_with_qa(
                session=session,
                repo=repo,
                job=job,
                scene=scene,
                aspect_ratios=aspect_ratios,
                initial_attempt_number=1,
                native_audio=native_audio,
                default_reference_uri=reference_image_uri or None,
                default_reference_mime_type=reference_image_mime_type,
            )
            scene_attempts.extend(attempts)
            final_attempt_number = max(int(item.get("attempt") or 1) for item in attempts)
            repo.update(
                scene,
                status="generated",
                data={
                    "attempt": final_attempt_number,
                    "latest_attempt_id": latest_attempt_ids.get(aspect_ratios[0]),
                    "latest_attempt_ids": latest_attempt_ids,
                    "output_uri": output_uris.get(aspect_ratios[0]),
                    "output_uris": output_uris,
                },
            )
        scenes = [dict(item.data) for item in scene_resources]
        repo.update(storyboard, data={"scenes": scenes})
        current_script = dict(script.data.get("script") or {})
        current_script.update(
            {
                "beats": scenes,
                "voiceover": " ".join(str(item.get("narration") or "").strip() for item in scenes).strip(),
            }
        )
        repo.update(script, data={"script": current_script})
        self._set_stage(repo, job, "scene_generation", "completed", output={"attempts": scene_attempts})

        self._set_stage(repo, job, "voice_audio", "running")
        audio_path = None
        if self.settings.uses_live_video and not native_audio:
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
        caption_asset_ids = await self._persist_caption_assets(repo=repo, job=job, scenes=scenes)
        self._set_stage(
            repo,
            job,
            "voice_audio",
            "completed",
            output={
                "provider": (
                    "veo_native_audio"
                    if native_audio
                    else "google_tts"
                    if self.settings.uses_live_video
                    else "deterministic_audio_bed"
                ),
                "audio_path": str(audio_path) if audio_path else None,
                "audio_storage_uri": audio_storage_uri,
                "caption_asset_id": caption_asset_ids["vtt"],
                "caption_srt_asset_id": caption_asset_ids["srt"],
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
            caption_asset_id=caption_asset_ids["vtt"],
            caption_srt_asset_id=caption_asset_ids["srt"],
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

    async def _persist_caption_assets(
        self,
        *,
        repo: ResourceRepository,
        job: Resource,
        scenes: list[dict[str, Any]],
    ) -> dict[str, str]:
        duration_seconds = int(job.data.get("target_duration_seconds", 30))
        caption_root = self.settings.storage_root / str(job.project_id) / job.id / "captions"
        outputs = (
            (
                "vtt",
                write_webvtt(
                    scenes=scenes,
                    output_path=caption_root / "captions.en.vtt",
                    duration_seconds=duration_seconds,
                ),
                "text/vtt",
            ),
            (
                "srt",
                write_srt(
                    scenes=scenes,
                    output_path=caption_root / "captions.en.srt",
                    duration_seconds=duration_seconds,
                ),
                "application/x-subrip",
            ),
        )
        asset_ids: dict[str, str] = {}
        for subtitle_format, path, mime_type in outputs:
            persisted = await asyncio.to_thread(self.storage.persist, path, content_type=mime_type)
            asset = repo.add(
                kind="media_asset",
                organization_id=job.organization_id,
                project_id=job.project_id,
                status="ready",
                data={
                    "generation_job_id": job.id,
                    "type": "captions",
                    "format": subtitle_format,
                    "storage_uri": persisted["storage_uri"],
                    "local_path": persisted["local_path"],
                    "public_path": persisted["public_path"],
                    "mime_type": mime_type,
                    "language": "en",
                    "rights_status": "owned",
                },
            )
            asset_ids[subtitle_format] = asset.id
        return asset_ids

    async def _materialize_brand_logo(
        self,
        *,
        session: Any,
        repo: ResourceRepository,
        job: Resource,
    ) -> Path | None:
        profile = session.scalar(
            select(Resource)
            .where(
                Resource.kind == "brand_profile",
                Resource.organization_id == job.organization_id,
                Resource.project_id == job.project_id,
            )
            .order_by(Resource.version.desc())
        )
        logo_refs = list(((profile.data if profile else {}).get("visual") or {}).get("logo_assets") or [])
        for logo_ref in logo_refs:
            asset_id = logo_ref.get("asset_id") if isinstance(logo_ref, dict) else None
            if not asset_id:
                continue
            asset = repo.get(
                str(asset_id),
                organization_id=job.organization_id,
                project_id=job.project_id,
                kind="media_asset",
            )
            if not asset or asset.data.get("type") != "brand_logo":
                continue
            local_value = asset.data.get("local_path")
            if not local_value:
                continue
            local_path = Path(str(local_value))
            await asyncio.to_thread(
                self.storage.materialize,
                storage_uri=asset.data.get("storage_uri"),
                local_path=local_path,
            )
            return local_path
        return None

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
        native_audio = job.data.get("audio_mode") == "veo_native"
        reference_image_uri = job.data.get("reference_image_uri")
        reference_image_mime_type = job.data.get("reference_image_mime_type")
        for scene in typed_scenes:
            latest_attempt_ids = dict(scene.data.get("latest_attempt_ids") or {})
            legacy_attempt_id = scene.data.get("latest_attempt_id")
            if legacy_attempt_id and aspect_ratios[0] not in latest_attempt_ids:
                latest_attempt_ids[aspect_ratios[0]] = str(legacy_attempt_id)
            output_uris = dict(scene.data.get("output_uris") or {})
            persisted_attempt_numbers = [
                int(item.data.get("attempt") or 0)
                for item in repo.list(
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    kind="scene_attempt",
                    limit=200,
                )
                if item.data.get("generation_job_id") == job.id
                and item.data.get("scene_id") == scene.id
            ]
            attempt_number = max(
                [int(scene.data.get("attempt", 0)), *persisted_attempt_numbers]
            )
            missing_ratios: list[str] = []
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
                    continuation_output_uri = latest_attempt.data.get("continuation_output_uri")
                    continuation_storage_uri = latest_attempt.data.get("continuation_storage_uri")
                    if continuation_output_uri and continuation_storage_uri:
                        await asyncio.to_thread(
                            self.storage.materialize,
                            storage_uri=continuation_storage_uri,
                            local_path=Path(str(continuation_output_uri)),
                        )
                    if output_uri and not latest_attempt.data.get("last_frame_storage_uri"):
                        last_frame_path = Path(output_uri).with_name(f"{Path(output_uri).stem}_last.jpg")
                        await asyncio.to_thread(extract_last_frame, Path(output_uri), last_frame_path)
                        persisted_last = await asyncio.to_thread(
                            self.storage.persist,
                            last_frame_path,
                            content_type="image/jpeg",
                        )
                        repo.update(
                            latest_attempt,
                            data={
                                "last_frame_storage_uri": persisted_last["storage_uri"],
                                "last_frame_public_path": persisted_last["public_path"],
                                "last_frame_mime_type": "image/jpeg",
                            },
                        )
                    scene_attempts.append(
                        {
                            "scene_id": scene.id,
                            "attempt_id": latest_attempt.id,
                            "attempt": latest_attempt.data.get("attempt"),
                            "aspect_ratio": aspect_ratio,
                            "model_id": latest_attempt.data.get("model_id"),
                            "output_uri": output_uri,
                            "storage_uri": storage_uri,
                            "public_path": latest_attempt.data.get("public_path"),
                            "continuation_output_uri": latest_attempt.data.get("continuation_output_uri"),
                            "continuation_storage_uri": latest_attempt.data.get("continuation_storage_uri"),
                            "speech_qa": latest_attempt.data.get("speech_qa"),
                            "voice_qa": latest_attempt.data.get("voice_qa"),
                            "last_frame_storage_uri": latest_attempt.data.get("last_frame_storage_uri"),
                        }
                    )
                    continue
                missing_ratios.append(aspect_ratio)
            if missing_ratios:
                generated, generated_ids, generated_uris = await self._generate_scene_with_qa(
                    session=session,
                    repo=repo,
                    job=job,
                    scene=scene,
                    aspect_ratios=missing_ratios,
                    initial_attempt_number=attempt_number + 1,
                    native_audio=native_audio,
                    default_reference_uri=reference_image_uri,
                    default_reference_mime_type=reference_image_mime_type,
                )
                scene_attempts.extend(generated)
                latest_attempt_ids.update(generated_ids)
                output_uris.update(generated_uris)
                attempt_number = max(int(item.get("attempt") or attempt_number + 1) for item in generated)
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
        scenes = [dict(item.data) for item in typed_scenes]
        repo.update(storyboard, data={"scenes": scenes})
        script_payload = dict(script.data.get("script") or {})
        script_payload.update(
            {
                "beats": scenes,
                "voiceover": " ".join(str(item.get("narration") or "").strip() for item in scenes).strip(),
            }
        )
        repo.update(script, data={"script": script_payload})
        self._set_stage(repo, job, "scene_generation", "completed", output={"attempts": scene_attempts})

        self._set_stage(repo, job, "voice_audio", "running")
        audio_path = None
        if self.settings.uses_live_video and not native_audio:
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
        caption_asset_ids = await self._persist_caption_assets(repo=repo, job=job, scenes=scenes)
        self._set_stage(
            repo,
            job,
            "voice_audio",
            "completed",
            output={
                "provider": (
                    "veo_native_audio"
                    if native_audio
                    else "google_tts"
                    if self.settings.uses_live_video
                    else "deterministic_audio_bed"
                ),
                "audio_path": str(audio_path) if audio_path else None,
                "audio_storage_uri": audio_storage_uri,
                "caption_asset_id": caption_asset_ids["vtt"],
                "caption_srt_asset_id": caption_asset_ids["srt"],
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
            caption_asset_id=caption_asset_ids["vtt"],
            caption_srt_asset_id=caption_asset_ids["srt"],
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
                item.setdefault("continuation_output_uri", persisted_attempt.data.get("continuation_output_uri"))
                item.setdefault("continuation_storage_uri", persisted_attempt.data.get("continuation_storage_uri"))
            output_uri = item.get("output_uri")
            if output_uri:
                await asyncio.to_thread(
                    self.storage.materialize,
                    storage_uri=item.get("storage_uri"),
                    local_path=Path(output_uri),
                )
            continuation_output_uri = item.get("continuation_output_uri")
            continuation_storage_uri = item.get("continuation_storage_uri")
            if continuation_output_uri and continuation_storage_uri:
                await asyncio.to_thread(
                    self.storage.materialize,
                    storage_uri=continuation_storage_uri,
                    local_path=Path(continuation_output_uri),
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
            caption_srt_asset_id=voice.get("caption_srt_asset_id"),
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
        caption_srt_asset_id: str | None,
        research_run_id: str,
    ) -> None:
        use_live_video = self.settings.uses_live_video and not bool(job.data.get("test_mode"))
        attempt_resources = repo.list(
            organization_id=job.organization_id,
            project_id=job.project_id,
            kind="scene_attempt",
            limit=200,
        )
        actual_billable_units = (
            sum(
                int(item.data.get("billable_seconds") or 0)
                for item in attempt_resources
                if item.data.get("generation_job_id") == job.id
            )
            if use_live_video
            else 0
        )
        settlement = settle_feature_charge(
            session,
            organization_id=job.organization_id,
            reference_id=job.id,
            actual_quantity=actual_billable_units,
        )
        repo.update(
            job,
            data={
                "actual_billable_units": actual_billable_units,
                "actual_cost_usd": round(settlement["customer_charge_cents"] / 100, 2),
                "actual_provider_cost_usd": settlement["provider_cost_usd"],
                "billing_refund_usd": round(settlement["refunded_cents"] / 100, 2),
                "platform_absorbed_customer_charge_usd": round(
                    settlement["absorbed_customer_charge_cents"] / 100, 2
                ),
            },
        )
        self._set_stage(repo, job, "render", "running")
        output_versions: list[dict[str, Any]] = []
        duration_seconds = int(job.data.get("target_duration_seconds", 30))
        project = repo.get_any(job.project_id or "", kind="project")
        brand_name = str(project.data.get("name") if project else "Framewise")
        logo_path = await self._materialize_brand_logo(session=session, repo=repo, job=job)
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
            matching_attempts = [
                item for item in scene_attempts if item.get("aspect_ratio") in {None, aspect_ratio}
            ]
            # The final timeline is always made from the authored per-scene tails in storyboard
            # order. Cumulative/rolling videos are private conditioning context for their own role;
            # rendering one of those would reorder interleaved characters and reintroduce hidden
            # in-model transitions. FFmpeg concat below is an instantaneous hard cut.
            scene_video_paths = [
                Path(str(item["output_uri"])) for item in matching_attempts if item.get("output_uri")
            ]
            manifest = await asyncio.to_thread(
                render_motion_video,
                title=title,
                brand_name=brand_name,
                scenes=scenes,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                output_path=output_path,
                scene_video_paths=scene_video_paths,
                audio_path=audio_path,
                use_scene_audio=job.data.get("audio_mode") == "veo_native",
                logo_path=logo_path,
                burn_in_captions=bool(job.data.get("burn_in_captions", False)),
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
            if job.data.get("test_mode"):
                # A deterministic fixture deliberately does not resemble the authored scene. Running
                # Gemini multimodal against it only produces a predictable false failure and spends a
                # model call on a capability that Test mode explicitly excludes.
                visual_qa = {
                    "passed": True,
                    "issues": [],
                    "scene_issues": [],
                    "unverified_scene_issues": [],
                    "continuity": 1.0,
                    "provider": "internal",
                    "model_id": "deterministic-test-fixture",
                    "skipped": True,
                    "skip_reason": "Video-dependent multimodal QA is not applicable to a Test mode fixture.",
                    "gates": {
                        "content": True,
                        "brand": True,
                        "platform": True,
                        "rights": True,
                    },
                }
            else:
                visual_qa = await self.multimodal_qa.analyze(
                    video_uri=persisted_render["storage_uri"],
                    scenes=scenes,
                    technical=qa,
                )
            # Every Test mode render intentionally uses the same deterministic fixture. It is
            # useful for exercising storage/rendering, but meaningless for creative deduplication.
            duplicate_passed = True if job.data.get("test_mode") else manifest["checksum"] not in existing_checksums
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
                    "logo_applied": manifest["logo_applied"],
                    "captions_burned_in": manifest["captions_burned_in"],
                    "overlay_style": manifest["overlay_style"],
                    "provenance": "generated" if use_live_video else "deterministic_mock",
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
            if use_live_video
            else all(item.get("model_id") == "deterministic-test-fixture" for item in scene_attempts)
        )
        rights_pass = provider_provenance_pass and all(
            item["multimodal_qa"].get("gates", {}).get("rights") is True for item in output_versions
        )
        duplicate_pass = all(item["duplicate_passed"] for item in output_versions)
        speech_pass = bool(scene_attempts) and all(
            bool((item.get("speech_qa") or {}).get("passed")) for item in scene_attempts
        )
        voice_identity_pass = (
            bool(scene_attempts)
            and all(bool((item.get("voice_qa") or {}).get("passed")) for item in scene_attempts)
            if job.data.get("audio_mode") == "veo_native"
            else True
        )
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
            "speech_timing": speech_pass,
            "voice_identity": voice_identity_pass,
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
            "speech": {
                "passed": speech_pass,
                "mode": "transcription" if job.data.get("audio_mode") == "veo_native" else "preflight_timing",
                "scenes": [
                    {
                        "scene_id": item.get("scene_id"),
                        "aspect_ratio": item.get("aspect_ratio"),
                        **dict(item.get("speech_qa") or {}),
                    }
                    for item in scene_attempts
                ],
            },
            "voice_identity": {
                "passed": voice_identity_pass,
                "preset": job.data.get("native_voice_preset"),
                "profile": job.data.get("native_voice_profile"),
                "seed": job.data.get("veo_seed"),
                "scenes": [
                    {
                        "scene_id": item.get("scene_id"),
                        "aspect_ratio": item.get("aspect_ratio"),
                        **dict(item.get("voice_qa") or {}),
                    }
                    for item in scene_attempts
                ],
            },
            "content": {
                "passed": content_pass and cta_present,
                "cta_present": cta_present,
                "claim_map_current": claim_map_current,
            },
            "brand": {
                "passed": brand_pass,
                "evaluated_by": "gemini_multimodal" if use_live_video else "deterministic_test_fixture",
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
            "duplicate": {
                "passed": duplicate_pass,
                "skipped": bool(job.data.get("test_mode")),
                "skip_reason": (
                    "Creative duplicate detection is not applicable to a shared Test mode fixture."
                    if job.data.get("test_mode")
                    else None
                ),
            },
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
            hard_gate_passed=qa_report_data["hard_gate_passed"],
            visual_pass=multimodal_pass,
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
                "evaluator_version": "score-v2-hard-gates",
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
                    "caption_srt_asset_id": caption_srt_asset_id,
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
                    "caption_srt_asset_id": caption_srt_asset_id,
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
                    "logo_applied": item["asset"].get("logo_applied", False),
                    "captions_burned_in": item["asset"].get("captions_burned_in", False),
                    "overlay_style": item["asset"].get("overlay_style", "none"),
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
                "actual_cost_usd": 0.0 if not use_live_video else job.data.get("actual_cost_usd"),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._complete_automatic_publications(
            session,
            repo,
            job,
            [item["id"] for item in versions],
            title=title,
        )
        logger.info(
            "generation_ready job_id=%s video_id=%s retry_source=%s",
            job.id,
            video.id,
            job.data.get("retry_source") or "initial",
        )
        await self._emit(
            session,
            job,
            "video.approval_required",
            {"video_id": video.id, "version_ids": [item["id"] for item in versions]},
        )
