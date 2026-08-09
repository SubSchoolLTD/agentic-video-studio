from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website_url: HttpUrl
    default_language: str = Field(default="en", min_length=2, max_length=12)
    regions: list[str] = Field(default_factory=lambda: ["US"])
    timezone: str = "UTC"
    analyze_website: bool = True
    rights_confirmed: bool = True


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    automation_mode: Literal["manual", "assisted", "auto_safe", "draft_only"] | None = None
    timezone: str | None = None
    settings: dict[str, Any] | None = None


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


class ResearchRunCreate(BaseModel):
    objective: str = Field(min_length=8, max_length=2_000)
    source_item_id: str | None = None
    recency_days: int = Field(default=30, ge=1, le=3650)
    max_candidates: int = Field(default=5, ge=1, le=20)


class IdeaCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    hook: str = Field(default="", max_length=500)
    audience: str = Field(min_length=2, max_length=200)
    objective: Literal["awareness", "traffic", "lead", "install", "purchase", "education"] = "education"
    format: str = "educational_explainer"
    source_item_id: str | None = None
    topic_candidate_id: str | None = None
    research_required: bool = True


class GenerationCreate(BaseModel):
    idea_id: str | None = None
    source_item_id: str | None = None
    title: str | None = Field(default=None, max_length=300)
    aspect_ratios: list[Literal["9:16", "16:9"]] = Field(default_factory=lambda: ["9:16"])
    target_duration_seconds: int = Field(default=30, ge=8, le=60)
    approval_mode: Literal["manual_all", "final_only", "auto_low_risk", "draft_only"] = "final_only"
    variants: int = Field(default=1, ge=1, le=3)
    max_cost_usd: float = Field(default=10, ge=0.1, le=1_000)

    @model_validator(mode="after")
    def require_input(self) -> GenerationCreate:
        if not (self.idea_id or self.source_item_id or self.title):
            raise ValueError("idea_id, source_item_id, or title is required")
        return self


class SceneRegenerate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    visual_prompt: str | None = Field(default=None, max_length=4_000)


class ReviewAction(BaseModel):
    reason_code: str | None = None
    comment: str | None = Field(default=None, max_length=2_000)


class PublicationCreate(BaseModel):
    video_version_id: str
    connection_id: str
    platform: Literal["youtube", "instagram", "tiktok", "export"]
    title: str = Field(min_length=3, max_length=300)
    caption: str = Field(default="", max_length=5_000)
    hashtags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    timezone: str = "UTC"
    privacy: Literal["private", "unlisted", "public"] | None = None
    commercial_content: bool = False
    synthetic_media_disclosure: bool = True
    made_for_kids: bool = False
    dry_run: bool = False


class PublicationConfirm(BaseModel):
    confirmation_token: str
    explicit_consent: bool = False


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)


class ConversionEventCreate(BaseModel):
    project_id: str
    publication_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    value: float = 1
    attribution: dict[str, Any] = Field(default_factory=dict)

