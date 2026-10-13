from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache

import httpx
from google.auth.credentials import Credentials

from .config import Settings


class TokenBrokerCredentials(Credentials):
    """Short-lived Google credentials refreshed through the narrow Cloud Run broker."""

    def __init__(self, broker_url: str, broker_secret: str):
        super().__init__()
        self.broker_url = broker_url.rstrip("/")
        self.broker_secret = broker_secret

    def refresh(self, request) -> None:  # noqa: ARG002
        response = httpx.post(
            f"{self.broker_url}/token",
            headers={"Authorization": f"Bearer {self.broker_secret}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "")
        expires_in = int(payload.get("expires_in") or 0)
        if not token or expires_in < 60:
            raise RuntimeError("Google token broker returned an invalid credential")
        self.token = token
        self.expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=expires_in - 30)


@lru_cache(maxsize=4)
def _broker_credentials(broker_url: str, broker_secret: str) -> TokenBrokerCredentials:
    return TokenBrokerCredentials(broker_url, broker_secret)


def google_cloud_credentials(settings: Settings) -> Credentials | None:
    if settings.google_token_broker_url and settings.google_token_broker_secret:
        return _broker_credentials(settings.google_token_broker_url, settings.google_token_broker_secret)
    return None
