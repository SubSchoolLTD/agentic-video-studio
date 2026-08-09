from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from apps.api.app.config import Settings
from apps.api.app.publishing import resolve_youtube_channel, youtube_authorization_url


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
