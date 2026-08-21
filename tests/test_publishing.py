from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from apps.api.app.config import Settings
from apps.api.app.publishing import (
    initiate_tiktok_post,
    resolve_youtube_channel,
    social_authorization_url,
    social_token_needs_refresh,
    youtube_authorization_url,
)


def test_social_oauth_urls_use_provider_callbacks_and_scopes() -> None:
    settings = Settings(
        _env_file=None,
        instagram_app_id="instagram-app",
        instagram_app_secret="instagram-secret",
        instagram_redirect_uri="https://api.example.test/v1/connections/instagram/callback",
        tiktok_client_key="tiktok-key",
        tiktok_client_secret="tiktok-secret",
        tiktok_redirect_uri="https://api.example.test/v1/connections/tiktok/callback",
    )

    instagram = parse_qs(urlparse(social_authorization_url(settings, provider="instagram", state="ig-state")).query)
    tiktok = parse_qs(urlparse(social_authorization_url(settings, provider="tiktok", state="tt-state")).query)

    assert instagram["state"] == ["ig-state"]
    assert instagram["redirect_uri"] == [settings.instagram_redirect_uri]
    assert set(instagram["scope"][0].split(",")) == {
        "instagram_business_basic",
        "instagram_business_content_publish",
    }
    assert tiktok["state"] == ["tt-state"]
    assert tiktok["redirect_uri"] == [settings.tiktok_redirect_uri]
    assert set(tiktok["scope"][0].split(",")) == {"user.info.basic", "video.publish"}


def test_social_token_refresh_window() -> None:
    assert social_token_needs_refresh(
        {"expires_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat()}
    )
    assert not social_token_needs_refresh(
        {"expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat()}
    )


@respx.mock
def test_tiktok_direct_post_uploads_generated_file(tmp_path) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"generated-video")
    secret_path = tmp_path / "tiktok.json"
    secret_path.write_text(json.dumps({"access_token": "access-token"}), encoding="utf-8")
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_id=upload-1&upload_token=token-1"
    initialize = respx.post("https://open.tiktokapis.com/v2/post/publish/video/init/").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"publish_id": "publish-1", "upload_url": upload_url},
                "error": {"code": "ok", "message": ""},
            },
        )
    )
    upload = respx.put(upload_url).mock(return_value=httpx.Response(201))

    result = initiate_tiktok_post(
        secret_ref=f"local:{secret_path}",
        file_path=video_path,
        title="A generated lesson",
        privacy_level="SELF_ONLY",
        allow_comments=True,
        allow_duet=False,
        allow_stitch=False,
        synthetic_media_disclosure=True,
    )

    request_body = json.loads(initialize.calls[0].request.content)
    assert result == {"publish_id": "publish-1"}
    assert request_body["post_info"]["is_aigc"] is True
    assert request_body["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": len(b"generated-video"),
        "chunk_size": len(b"generated-video"),
        "total_chunk_count": 1,
    }
    assert upload.calls[0].request.headers["content-range"] == "bytes 0-14/15"


def test_youtube_pkce_verifier_is_persistable() -> None:
    settings = Settings(
        _env_file=None,
        youtube_client_id="client.apps.googleusercontent.com",
        youtube_client_secret="client-secret",
        youtube_redirect_uri="https://example.test/v1/connections/youtube/callback",
    )

    url, verifier = youtube_authorization_url(settings, state="state-123")
    query = parse_qs(urlparse(url).query)

    assert len(verifier) == 128
    assert query["state"] == ["state-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]


def test_youtube_connection_resolves_selected_channel() -> None:
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "UC_subschool",
                "snippet": {"title": "SubSchool"},
                "status": {"privacyStatus": "public"},
            }
        ]
    }
    settings = Settings(
        _env_file=None,
        youtube_client_id="client.apps.googleusercontent.com",
        youtube_client_secret="client-secret",
    )
    with patch("googleapiclient.discovery.build", return_value=youtube):
        channel = resolve_youtube_channel(
            settings,
            {
                "token": "access",
                "refresh_token": "refresh",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
            },
        )
    assert channel["id"] == "UC_subschool"
    assert channel["title"] == "SubSchool"
