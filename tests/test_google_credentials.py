from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from apps.api.app.config import Settings
from apps.api.app.google_credentials import TokenBrokerCredentials, google_cloud_credentials


@respx.mock
def test_token_broker_credentials_refresh_with_short_lived_token() -> None:
    route = respx.post("https://broker.example.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "short-lived-token", "expires_in": 3600})
    )
    credentials = TokenBrokerCredentials(
        "https://broker.example.com/",
        "broker-test-secret-longer-than-thirty-two-characters",
    )

    credentials.refresh(None)

    assert route.called
    assert route.calls[0].request.headers["Authorization"].startswith("Bearer broker-test-secret")
    assert credentials.token == "short-lived-token"
    assert credentials.expiry is not None
    assert credentials.expiry > datetime.now(UTC).replace(tzinfo=None)


def test_google_cloud_credentials_are_optional() -> None:
    assert google_cloud_credentials(Settings()) is None
