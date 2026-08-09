from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_auth_mode: str = "demo"
    app_demo_token: str = "demo-token"
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    database_url: str = "sqlite:///./local_data/agentic_video_studio.sqlite3"
    storage_root: Path = Path("./local_data/media")
    provider_mode: str = "mock"
    log_level: str = "INFO"

    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_cloud_storage_bucket: str = ""
    google_application_credentials: str = ""
    google_runtime_service_account: str = ""
    google_pubsub_topic: str = ""
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_local_directories()
    return settings
