from __future__ import annotations

from pathlib import Path


def test_production_deploy_targets_ovh_and_keeps_dynamic_oauth_state_local() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "deploy.yml").read_text()
    compose = (Path(__file__).parents[1] / "docker-compose.production.yml").read_text()

    for setting in (
        '"APP_BASE_URL": "https://studio.subschool.us"',
        '"WEB_BASE_URL": "https://studio.subschool.us"',
        '"YOUTUBE_REDIRECT_URI": "https://studio.subschool.us/v1/connections/youtube/callback"',
        '"OAUTH_SECRET_BACKEND": "local"',
    ):
        assert setting in workflow

    assert "137.74.202.47" in workflow
    assert "GOOGLE_TOKEN_BROKER_SECRET" in workflow
    assert "framewise-google-token-broker" in workflow
    assert "google-github-actions/auth@v2" in workflow
    assert "social-browser-sessions" not in workflow
    assert "MEDIA_STORAGE_BACKEND: local" in compose
    assert "OAUTH_SECRET_BACKEND: local" in compose
    assert "framewise_postgres_data" in compose
    assert "caddy_net" in compose
