from pathlib import Path

import pytest

from apps.api.app.config import Settings
from apps.api.app.storage import MediaStorage


def test_materialize_uses_local_mirror_for_migrated_gcs_asset(tmp_path: Path) -> None:
    storage_root = tmp_path / "media"
    mirrored = storage_root / "project" / "render.mp4"
    mirrored.parent.mkdir(parents=True)
    mirrored.write_bytes(b"migrated-video")
    target = tmp_path / "legacy-cloud-run" / "render.mp4"
    storage = MediaStorage(
        Settings(
            storage_root=storage_root,
            media_storage_backend="local",
            google_cloud_storage_bucket="legacy-bucket",
        )
    )

    result = storage.materialize(
        storage_uri="gs://legacy-bucket/project/render.mp4",
        local_path=target,
    )

    assert result == target
    assert target.read_bytes() == b"migrated-video"


def test_materialize_does_not_fall_back_to_gcs_when_local_backend_is_selected(tmp_path: Path) -> None:
    storage = MediaStorage(
        Settings(
            storage_root=tmp_path / "media",
            media_storage_backend="local",
            google_cloud_storage_bucket="legacy-bucket",
        )
    )

    with pytest.raises(FileNotFoundError):
        storage.materialize(
            storage_uri="gs://legacy-bucket/project/missing.mp4",
            local_path=tmp_path / "legacy-cloud-run" / "missing.mp4",
        )
