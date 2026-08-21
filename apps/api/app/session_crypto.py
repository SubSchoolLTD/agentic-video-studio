from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import Settings


class BrowserSessionCryptoError(RuntimeError):
    """Raised when an encrypted browser session cannot be authenticated."""


def _master_key(settings: Settings) -> bytes:
    configured = settings.secret_encryption_key or settings.jwt_secret
    if not configured:
        raise BrowserSessionCryptoError("Browser session encryption is not configured")
    return hashlib.sha256(b"framewise:browser-session:v1\x00" + configured.encode("utf-8")).digest()


def _aad(*, connection_id: str, organization_id: str, project_id: str, provider: str) -> bytes:
    return json.dumps(
        [connection_id, organization_id, project_id, provider],
        separators=(",", ":"),
    ).encode("utf-8")


def encrypt_browser_session(
    settings: Settings,
    *,
    connection_id: str,
    organization_id: str,
    project_id: str,
    provider: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_master_key(settings)).encrypt(
        nonce,
        plaintext,
        _aad(
            connection_id=connection_id,
            organization_id=organization_id,
            project_id=project_id,
            provider=provider,
        ),
    )
    return {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_browser_session(
    settings: Settings,
    *,
    connection_id: str,
    organization_id: str,
    project_id: str,
    provider: str,
    envelope: object,
) -> dict[str, Any]:
    if not isinstance(envelope, dict) or envelope.get("version") != 1:
        raise BrowserSessionCryptoError("Browser session is unavailable")
    if envelope.get("algorithm") != "AES-256-GCM":
        raise BrowserSessionCryptoError("Browser session encryption format is unsupported")
    try:
        nonce = base64.urlsafe_b64decode(str(envelope["nonce"]).encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(str(envelope["ciphertext"]).encode("ascii"))
        plaintext = AESGCM(_master_key(settings)).decrypt(
            nonce,
            ciphertext,
            _aad(
                connection_id=connection_id,
                organization_id=organization_id,
                project_id=project_id,
                provider=provider,
            ),
        )
        payload = json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrowserSessionCryptoError("Browser session could not be authenticated") from exc
    if not isinstance(payload, dict):
        raise BrowserSessionCryptoError("Browser session payload is invalid")
    return payload
