from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    primary_language: str = Field(default="en", min_length=2, max_length=12)
    timezone: str = "UTC"
    default_currency: str = Field(default="USD", min_length=3, max_length=3)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website_url: HttpUrl
    default_language: str = Field(default="en", min_length=2, max_length=12)
    regions: list[str] = Field(default_factory=lambda: ["US"])
    timezone: str = "UTC"
    analyze_website: bool = True
    rights_confirmed: bool = True
    brief: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    automation_mode: Literal["manual", "assisted", "auto_safe", "draft_only"] | None = None
    timezone: str | None = None
    settings: dict[str, Any] | None = None
    brief: dict[str, Any] | None = None


class BrandProfilePatch(BaseModel):
    description: str | None = None
    audiences: dict[str, list[str]] | None = None
    value_propositions: list[str] | None = None
    tone: dict[str, list[str]] | None = None
    claims: dict[str, list[str]] | None = None
    visual: dict[str, Any] | None = None
    cta: dict[str, Any] | None = None
    compliance: dict[str, Any] | None = None
    confirmed: bool = True


class SourceCreate(BaseModel):
    type: Literal["website", "rss", "api", "manual", "text", "url"]
    name: str = Field(min_length=2, max_length=160)
    url: HttpUrl | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    url: HttpUrl | None = None
    config: dict[str, Any] | None = None
    generation_policy: Literal["research_then_approval", "draft_only", "auto_safe"] | None = None
    status: Literal["healthy", "paused"] | None = None


class SourceItemCreate(BaseModel):
    source_type: Literal["url", "text", "rss", "api", "monitor", "manual"]
    external_id: str | None = None
    canonical_url: HttpUrl | None = None
    title: str = Field(min_length=3, max_length=300)
    content_markdown: str = Field(default="", max_length=500_000)
    language: str = "en"
    published_at: datetime | None = None
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    rights_confirmed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    processing: dict[str, Any] = Field(default_factory=dict)
    callback_url: HttpUrl | None = None


class ContentItemCreate(BaseModel):
    project_id: str
    external_id: str | None = None
    type: Literal["article", "idea", "text", "url"] = "article"
    title: str = Field(min_length=3, max_length=300)
    url: HttpUrl | None = None
    content: str = Field(default="", max_length=500_000)
    language: str = "en"
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    automation: dict[str, Any] = Field(default_factory=dict)
    callback_url: HttpUrl | None = None
    rights_confirmed: bool = True


class TopicMute(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    muted_until: datetime | None = None
    permanent: bool = False


class ResearchRunCreate(BaseModel):
    objective: str = Field(min_length=8, max_length=2_000)
    source_item_id: str | None = None
    recency_days: int = Field(default=30, ge=1, le=3650)
    max_candidates: int = Field(default=5, ge=1, le=20)


class ResearchProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    objective: str = Field(min_length=8, max_length=2_000)
    interval_hours: int = Field(default=24, ge=1, le=24 * 30)
    timezone: str = "UTC"
    recency_days: int = Field(default=30, ge=1, le=3650)
    max_candidates: int = Field(default=5, ge=1, le=20)
    next_run_at: datetime | None = None


class ResearchProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    objective: str | None = Field(default=None, min_length=8, max_length=2_000)
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    timezone: str | None = None
    recency_days: int | None = Field(default=None, ge=1, le=3650)
    max_candidates: int | None = Field(default=None, ge=1, le=20)
    status: Literal["active", "paused"] | None = None


class IdeaCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    hook: str = Field(default="", max_length=500)
    audience: str = Field(min_length=2, max_length=200)
    objective: Literal["awareness", "traffic", "lead", "install", "purchase", "education"] = "education"
    format: str = "educational_explainer"
    visual_mode: Literal[
        "ugc_creator", "ugc_native_audio", "storytelling", "cinematic", "motion_graphics"
    ] = "ugc_creator"
    audio_mode: Literal["google_tts", "veo_native"] | None = None
    native_voice_preset: Literal[
        "warm_conversational", "calm_expert", "bright_creator", "grounded_storyteller"
    ] = "warm_conversational"
    character_id: str | None = Field(default=None, max_length=64)
    source_item_id: str | None = None
    topic_candidate_id: str | None = None
    research_required: bool = True


class IdeaPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    hook: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, min_length=2, max_length=200)
    objective: Literal["awareness", "traffic", "lead", "install", "purchase", "education"] | None = None
    format: str | None = Field(default=None, max_length=120)
    visual_mode: Literal[
        "ugc_creator", "ugc_native_audio", "storytelling", "cinematic", "motion_graphics"
    ] | None = None
    audio_mode: Literal["google_tts", "veo_native"] | None = None
    native_voice_preset: Literal[
        "warm_conversational", "calm_expert", "bright_creator", "grounded_storyteller"
    ] | None = None
    character_id: str | None = Field(default=None, max_length=64)
    status: Literal["draft", "researching", "ready", "planned"] | None = None


class GenerationCreate(BaseModel):
    idea_id: str | None = None
    source_item_id: str | None = None
    title: str | None = Field(default=None, max_length=300)
    aspect_ratios: list[Literal["9:16", "16:9"]] = Field(default_factory=lambda: ["9:16"])
    target_duration_seconds: int = Field(default=30, ge=8)
    approval_mode: Literal["manual_all", "final_only", "auto_low_risk", "draft_only"] = "final_only"
    variants: int = Field(default=1, ge=1, le=3)
    visual_mode: Literal[
        "ugc_creator", "ugc_native_audio", "storytelling", "cinematic", "motion_graphics"
    ] | None = None
    audio_mode: Literal["google_tts", "veo_native"] | None = None
    continue_scenes: bool | None = None
    native_voice_preset: Literal[
        "warm_conversational", "calm_expert", "bright_creator", "grounded_storyteller"
    ] | None = None
    character_id: str | None = Field(default=None, max_length=64)
    scene_count_min: int = Field(default=4, ge=2, le=2_000)
    scene_count_max: int = Field(default=6, ge=2, le=2_000)
    scene_count_flex: int = Field(default=2, ge=0, le=2)
    burn_in_captions: bool = False
    generation_start_mode: Literal["immediate", "review_script"] = "immediate"
    test_mode: bool = False
    max_cost_usd: float = Field(default=30, ge=0.1)

    @model_validator(mode="after")
    def require_input(self) -> GenerationCreate:
        if not (self.idea_id or self.source_item_id or self.title):
            raise ValueError("idea_id, source_item_id, or title is required")
        if self.scene_count_min > self.scene_count_max:
            raise ValueError("scene_count_min cannot be greater than scene_count_max")
        return self


class CharacterGenerate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    prompt: str = Field(min_length=8, max_length=2_000)


class SceneRegenerate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    visual_prompt: str | None = Field(default=None, max_length=4_000)


class ScriptPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    hook: str | None = Field(default=None, min_length=3, max_length=500)
    voiceover: str | None = Field(default=None, min_length=3, max_length=8_000)
    cta: str | None = Field(default=None, max_length=500)
    caption_candidates: list[str] | None = None
    hashtags: list[str] | None = None
    reason: str = Field(min_length=8, max_length=2_000)


class ProductionScenePatch(BaseModel):
    narration: str = Field(min_length=1, max_length=2_000)
    speaker: str = Field(default="", max_length=160)
    speaker_kind: Literal["on_camera", "voice_over", "silent"] = "on_camera"
    purpose: str = Field(min_length=3, max_length=1_000)
    story_beat: str = Field(min_length=3, max_length=1_000)
    subject: str = Field(min_length=3, max_length=2_000)
    setting: str = Field(min_length=3, max_length=2_000)
    action: str = Field(min_length=3, max_length=2_000)
    environment_detail: str = Field(default="", max_length=2_000)
    blocking: str = Field(default="", max_length=2_000)
    camera_direction: str = Field(default="", max_length=2_000)
    performance_direction: str = Field(default="", max_length=2_000)
    sound_direction: str = Field(default="", max_length=2_000)
    fragment_intent: str = Field(default="", max_length=2_000)
    dialogue_intent: str = Field(default="", max_length=2_000)
    dramatic_conflict: str = Field(default="", max_length=2_000)
    audience_value: str = Field(default="", max_length=2_000)
    emotional_change: str = Field(default="", max_length=2_000)


class ProductionScriptRegenerate(BaseModel):
    feedback: str = Field(min_length=8, max_length=4_000)


class ReviewAction(BaseModel):
    reason_code: str | None = None
    comment: str | None = Field(default=None, max_length=2_000)


class ScoreOverride(BaseModel):
    score: Literal["publish_readiness", "predicted_performance"]
    value: int = Field(ge=0, le=100)
    reason: str = Field(min_length=8, max_length=2_000)


class PublicationCreate(BaseModel):
    video_version_id: str
    connection_id: str
    platform: Literal["youtube", "instagram", "tiktok", "export"]
    title: str = Field(min_length=3, max_length=300)
    caption: str = Field(default="", max_length=5_000)
    hashtags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    timezone: str = "UTC"
    privacy: Literal[
        "private",
        "unlisted",
        "public",
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "FOLLOWER_OF_CREATOR",
        "SELF_ONLY",
    ] | None = None
    commercial_content: bool = False
    synthetic_media_disclosure: bool = True
    made_for_kids: bool = False
    allow_comments: bool | None = None
    allow_duet: bool | None = None
    allow_stitch: bool | None = None
    creator_info_acknowledged: bool = False
    dry_run: bool = False


class PublicationConfirm(BaseModel):
    confirmation_token: str
    explicit_consent: bool = False


class SocialBrowserLogin(BaseModel):
    username: str = Field(min_length=2, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=512)


class SocialBrowserVerification(BaseModel):
    code: SecretStr = Field(min_length=4, max_length=16)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)


class WebhookPatch(BaseModel):
    url: HttpUrl | None = None
    events: list[str] | None = Field(default=None, min_length=1)
    status: Literal["active", "paused"] | None = None


class ConversionEventCreate(BaseModel):
    project_id: str
    publication_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    value: float = 1
    attribution: dict[str, Any] = Field(default_factory=dict)
