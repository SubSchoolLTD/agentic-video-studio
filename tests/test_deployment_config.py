from __future__ import annotations

from pathlib import Path


def test_production_deploy_wires_public_oauth_callbacks_and_optional_secrets() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "deploy.yml").read_text()

    for setting in (
        "APP_BASE_URL=${PRODUCTION_API_URL}",
        "WEB_BASE_URL=${PRODUCTION_WEB_URL}",
        "YOUTUBE_REDIRECT_URI=${PRODUCTION_API_URL}/v1/connections/youtube/callback",
        "INSTAGRAM_REDIRECT_URI=${PRODUCTION_API_URL}/v1/connections/instagram/callback",
        "TIKTOK_REDIRECT_URI=${PRODUCTION_API_URL}/v1/connections/tiktok/callback",
    ):
        assert setting in workflow

    assert 'if [[ "${ATTACH_SOCIAL_SECRETS}" == "true" ]]' in workflow
    for binding in (
        "INSTAGRAM_APP_ID=instagram-app-id:latest",
        "INSTAGRAM_APP_SECRET=instagram-app-secret:latest",
        "TIKTOK_CLIENT_KEY=tiktok-client-key:latest",
        "TIKTOK_CLIENT_SECRET=tiktok-client-secret:latest",
    ):
        assert binding in workflow

