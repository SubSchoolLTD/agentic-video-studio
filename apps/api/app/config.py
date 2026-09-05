from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_auth_mode: str = "jwt"
    app_demo_token: str = "demo-token"
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    database_url: str = "sqlite:///./local_data/agentic_video_studio.sqlite3"
    storage_root: Path = Path("./local_data/media")
    provider_mode: str = "mock"
    log_level: str = "INFO"

    jwt_secret: str = "development-only-change-me"
    jwt_issuer: str = "agentic-video-studio"
    jwt_audience: str = "agentic-video-studio-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    email_token_minutes: int = 60
    password_reset_minutes: int = 30
    email_min_resend_seconds: int = 60
    email_max_per_hour: int = 5
    email_delivery_mode: str = "log"
    email_from_name: str = "Framewise"
    email_from_email: str = "maksim@subschool.us"
    sendpulse_id: str = ""
    sendpulse_secret: str = ""
    sendpulse_template_id: str = ""
    sendpulse_template_name: str = ""
    bootstrap_admin_email: str = ""
    bootstrap_admin_name: str = "Maksim Mamchur"
    seed_demo_data: bool = False
    test_support_secret: str = "test-support-only"

    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_min_topup_usd: int = 12

    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_cloud_storage_bucket: str = ""
    google_application_credentials: str = ""
    google_runtime_service_account: str = ""
    google_pubsub_topic: str = ""
    google_api_key: str = ""
    google_oauth_client_id: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_editorial_model: str = "gemini-2.5-pro"
    gemini_quality_model: str = "gemini-2.5-pro"
    google_image_model: str = "gemini-2.5-flash-image"
    veo_model: str = "veo-3.1-generate-001"
    google_tts_voice: str = "en-US-Chirp3-HD-Achernar"
    google_genai_use_vertexai: bool = True

    parallel_api_key: str = ""
    parallel_base_url: str = "https://api.parallel.ai"
    parallel_search_endpoint: str = "/v1/search"

    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/v1/connections/youtube/callback"
    youtube_refresh_token: str = ""
    youtube_refresh_token_secret: str = "youtube-refresh-token"
    youtube_channel_id: str = ""

    social_browser_headless: bool = True
    social_browser_timeout_seconds: int = 120
    social_browser_instagram_base_url: str = "https://www.instagram.com"
    social_browser_tiktok_base_url: str = "https://www.tiktok.com"

    clickhouse_url: str = ""
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    grafana_otlp_endpoint: str = ""
    grafana_otlp_headers: str = ""
    grafana_url: str = ""

    webhook_signing_secret: str = "development-webhook-secret"
    api_key_pepper: str = "development-api-key-pepper"
    secret_encryption_key: str = ""
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_mock(self) -> bool:
        return self.provider_mode == "mock"

    @property
    def uses_live_research(self) -> bool:
        return self.provider_mode in {"hybrid", "live"}

    @property
    def uses_live_video(self) -> bool:
        return self.provider_mode == "live"

    def ensure_local_directories(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            database_path = self.database_url.rsplit("/", maxsplit=1)[-1]
            if database_path and database_path != ":memory:":
                Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    def validate_runtime(self) -> None:
        if self.app_env in {"production", "prod"}:
            if self.app_auth_mode != "jwt":
                raise RuntimeError("Production requires APP_AUTH_MODE=jwt")
            if self.jwt_secret in {"", "development-only-change-me"} or len(self.jwt_secret) < 32:
                raise RuntimeError("Production requires a strong JWT_SECRET")
            if self.provider_mode != "live":
                raise RuntimeError("Production requires PROVIDER_MODE=live")
            missing = []
            if not self.parallel_api_key:
                missing.append("PARALLEL_API_KEY")
            if not self.google_cloud_project:
                missing.append("GOOGLE_CLOUD_PROJECT")
            if not self.google_cloud_storage_bucket:
                missing.append("GOOGLE_CLOUD_STORAGE_BUCKET")
            if self.email_delivery_mode != "sendpulse":
                missing.append("EMAIL_DELIVERY_MODE=sendpulse")
            if not self.sendpulse_id:
                missing.append("SENDPULSE_ID")
            if not self.sendpulse_secret:
                missing.append("SENDPULSE_SECRET")
            if self.paypal_env != "live":
                missing.append("PAYPAL_ENV=live")
            if not self.paypal_client_id:
                missing.append("PAYPAL_CLIENT_ID")
            if not self.paypal_secret:
                missing.append("PAYPAL_SECRET")
            if self.social_browser_instagram_base_url.rstrip("/") != "https://www.instagram.com":
                missing.append("SOCIAL_BROWSER_INSTAGRAM_BASE_URL=https://www.instagram.com")
            if self.social_browser_tiktok_base_url.rstrip("/") != "https://www.tiktok.com":
                missing.append("SOCIAL_BROWSER_TIKTOK_BASE_URL=https://www.tiktok.com")
            if missing:
                raise RuntimeError(f"Production configuration is incomplete: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_local_directories()
    settings.validate_runtime()
    return settings
