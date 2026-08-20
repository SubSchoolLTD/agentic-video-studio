from __future__ import annotations

import pytest

from apps.api.app.config import Settings


def test_prod_alias_enforces_fail_closed_runtime_validation() -> None:
    settings = Settings(app_env="prod", app_auth_mode="demo", provider_mode="mock")
    with pytest.raises(RuntimeError, match="APP_AUTH_MODE=jwt"):
        settings.validate_runtime()


def test_prod_alias_accepts_complete_live_configuration() -> None:
    settings = Settings(
        app_env="prod",
        app_auth_mode="jwt",
        jwt_secret="production-test-secret-longer-than-thirty-two-characters",
        provider_mode="live",
        parallel_api_key="parallel-test",
        google_cloud_project="production-test",
        google_cloud_storage_bucket="production-test-media",
        email_delivery_mode="sendpulse",
        sendpulse_id="sendpulse-test",
        sendpulse_secret="sendpulse-secret-test",
        paypal_env="live",
        paypal_client_id="paypal-client-test",
        paypal_secret="paypal-secret-test",
    )
    settings.validate_runtime()
