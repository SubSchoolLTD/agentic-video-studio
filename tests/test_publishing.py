from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from apps.api.app.publishing import (
    resolve_youtube_channel,
    youtube_authorization_url,
)
from apps.api.app.repository import ResourceRepository


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


def test_youtube_callback_closes_oauth_popup_and_notifies_framewise(client) -> None:
    state = "youtube-popup-callback-state"
    with SessionLocal() as session:
        ResourceRepository(session).add(
            kind="oauth_state",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="pending",
            data={
                "provider": "youtube",
                "state": state,
                "code_verifier": "pkce-verifier",
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
        )

    token_data = {
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    with (
        patch("apps.api.app.routes.exchange_youtube_code", return_value=token_data),
        patch(
            "apps.api.app.routes.resolve_youtube_channel",
            return_value={"id": "UC_framewise", "title": "Framewise", "privacy_status": "public"},
        ),
        patch("apps.api.app.routes.store_oauth_secret", return_value="local:test-youtube-secret"),
    ):
        response = client.get(
            "/v1/connections/youtube/callback",
            params={"code": "authorization-code", "state": state},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "YouTube connected" in response.text
    assert "framewise-oauth-connected" in response.text
    assert "window.close()" in response.text
    assert response.headers["cache-control"] == "no-store"
