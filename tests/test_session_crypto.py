from __future__ import annotations

import pytest

from apps.api.app.config import Settings
from apps.api.app.session_crypto import (
    BrowserSessionCryptoError,
    decrypt_browser_session,
    encrypt_browser_session,
)


def _settings() -> Settings:
    return Settings(_env_file=None, secret_encryption_key="test-browser-session-key")


def test_browser_session_round_trip_is_encrypted() -> None:
    settings = _settings()
    payload = {
        "provider": "instagram",
        "storage_state": {"cookies": [{"name": "sessionid", "value": "sensitive"}], "origins": []},
    }
    envelope = encrypt_browser_session(
        settings,
        connection_id="conne_1",
        organization_id="org_1",
        project_id="prj_1",
        provider="instagram",
        payload=payload,
    )

    assert envelope["algorithm"] == "AES-256-GCM"
    assert "sensitive" not in envelope["ciphertext"]
    assert decrypt_browser_session(
        settings,
        connection_id="conne_1",
        organization_id="org_1",
        project_id="prj_1",
        provider="instagram",
        envelope=envelope,
    ) == payload


def test_browser_session_is_bound_to_tenant_and_connection() -> None:
    settings = _settings()
    envelope = encrypt_browser_session(
        settings,
        connection_id="conne_1",
        organization_id="org_1",
        project_id="prj_1",
        provider="tiktok",
        payload={"provider": "tiktok", "storage_state": {"cookies": [], "origins": []}},
    )

    with pytest.raises(BrowserSessionCryptoError):
        decrypt_browser_session(
            settings,
            connection_id="conne_1",
            organization_id="org_other",
            project_id="prj_1",
            provider="tiktok",
            envelope=envelope,
        )


def test_browser_session_rejects_tampered_ciphertext() -> None:
    settings = _settings()
    envelope = encrypt_browser_session(
        settings,
        connection_id="conne_1",
        organization_id="org_1",
        project_id="prj_1",
        provider="instagram",
        payload={"provider": "instagram", "storage_state": {"cookies": [], "origins": []}},
    )
    replacement = "B" if envelope["ciphertext"].startswith("A") else "A"
    envelope["ciphertext"] = f"{replacement}{envelope['ciphertext'][1:]}"

    with pytest.raises(BrowserSessionCryptoError):
        decrypt_browser_session(
            settings,
            connection_id="conne_1",
            organization_id="org_1",
            project_id="prj_1",
            provider="instagram",
            envelope=envelope,
        )
