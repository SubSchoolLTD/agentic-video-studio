from __future__ import annotations

import hashlib
import hmac
import mimetypes
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .config import Settings


class MediaStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.google_cloud_storage_bucket)

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=self.settings.google_cloud_project or None)
        return self._client.bucket(self.settings.google_cloud_storage_bucket)

    def relative_path(self, local_path: Path) -> str:
        return local_path.resolve().relative_to(self.settings.storage_root.resolve()).as_posix()

    def persist(self, local_path: Path, *, content_type: str | None = None) -> dict[str, str]:
        relative = self.relative_path(local_path)
        storage_uri = str(local_path)
        if self.enabled:
            blob = self._bucket().blob(relative)
            blob.upload_from_filename(
                str(local_path),
                content_type=content_type or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream",
                timeout=180,
            )
            storage_uri = f"gs://{self.settings.google_cloud_storage_bucket}/{relative}"
        return {
            "local_path": str(local_path),
            "storage_uri": storage_uri,
            "public_path": f"/media/{relative}",
        }

    def signed_path(self, public_path: str, organization_id: str, *, ttl_seconds: int = 3600) -> str:
        clean = public_path.split("?", 1)[0]
        expires = int(time.time()) + ttl_seconds
        message = f"{clean}:{organization_id}:{expires}".encode()
        signature = hmac.new(self.settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()
        return f"{clean}?org={quote(organization_id, safe='')}&expires={expires}&sig={signature}"

    def public_path_for(self, *, storage_uri: str | None = None, local_path: str | None = None) -> str | None:
        """Resolve a persisted private object to the authenticated media route."""
        if storage_uri and storage_uri.startswith("gs://"):
            prefix = f"gs://{self.settings.google_cloud_storage_bucket}/"
            if storage_uri.startswith(prefix):
                relative = storage_uri.removeprefix(prefix)
                return f"/media/{relative}"
        raw_path = local_path or storage_uri
        if raw_path:
            candidate = Path(raw_path)
            try:
                return f"/media/{self.relative_path(candidate)}"
            except (ValueError, OSError):
                return None
        return None

    def verify_signed_path(self, public_path: str, organization_id: str, expires: int, signature: str) -> bool:
        if expires < int(time.time()) or expires > int(time.time()) + 86400:
            return False
        message = f"{public_path}:{organization_id}:{expires}".encode()
        expected = hmac.new(self.settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def materialize(self, *, storage_uri: str | None, local_path: Path) -> Path:
        if local_path.exists():
            return local_path
        if not storage_uri or not storage_uri.startswith("gs://"):
            raise FileNotFoundError(local_path)
        prefix = f"gs://{self.settings.google_cloud_storage_bucket}/"
        if not storage_uri.startswith(prefix):
            raise ValueError("Media object is outside the configured bucket")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._bucket().blob(storage_uri.removeprefix(prefix)).download_to_filename(str(local_path), timeout=180)
        return local_path

    def resolve_local(self, asset_path: str) -> Path | None:
        relative = PurePosixPath(asset_path)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        root = self.settings.storage_root.resolve()
        candidate = (root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(root):
            return None
        return candidate

    def download_bytes(self, asset_path: str) -> tuple[bytes, str] | None:
        relative = PurePosixPath(asset_path)
        if not self.enabled or relative.is_absolute() or ".." in relative.parts:
            return None
        blob = self._bucket().blob(relative.as_posix())
        if not blob.exists():
            return None
        blob.reload()
        return (
            blob.download_as_bytes(timeout=180),
            blob.content_type or mimetypes.guess_type(asset_path)[0] or "application/octet-stream",
        )
