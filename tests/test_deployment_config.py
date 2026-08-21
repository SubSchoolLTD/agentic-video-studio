from __future__ import annotations

from pathlib import Path


def test_production_deploy_wires_youtube_and_browser_session_storage() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "deploy.yml").read_text()

    for setting in (
        "APP_BASE_URL=${PRODUCTION_API_URL}",
        "WEB_BASE_URL=${PRODUCTION_WEB_URL}",
        "YOUTUBE_REDIRECT_URI=${PRODUCTION_API_URL}/v1/connections/youtube/callback",
        "SOCIAL_BROWSER_SESSION_SECRET=social-browser-sessions",
    ):
        assert setting in workflow

    assert "ATTACH_SOCIAL_SECRETS" not in workflow
    assert "INSTAGRAM_APP_ID=instagram-app-id:latest" not in workflow
    assert "TIKTOK_CLIENT_KEY=tiktok-client-key:latest" not in workflow
    assert "--remove-env-vars=APP_DEMO_TOKEN,INSTAGRAM_APP_ID" in workflow
