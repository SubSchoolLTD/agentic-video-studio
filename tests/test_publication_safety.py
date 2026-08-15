from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.publishing import get_youtube_video_status
from apps.api.app.renderer import render_motion_video, write_webvtt
from apps.api.app.repository import ResourceRepository


def _approved_version(*, with_media: bool = False) -> str:
    settings = get_settings()
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        suffix = ResourceRepository.new_id("safe")
        caption_asset_id = None
        if with_media:
            root = settings.storage_root / "prj_subschool" / suffix
            video_path = root / "video.mp4"
            render_motion_video(
                title="Safe export",
                brand_name="SubSchool",
                scenes=[{"purpose": "Test", "on_screen_text": "Export package"}],
                aspect_ratio="9:16",
                duration_seconds=2,
                output_path=video_path,
            )
            caption_path = write_webvtt(
                scenes=[{"narration": "Export package"}],
                output_path=root / "captions.vtt",
                duration_seconds=2,
            )
            caption_asset = repo.add(
                kind="media_asset",
                organization_id="org_demo",
                project_id="prj_subschool",
                status="ready",
                data={
                    "type": "captions",
                    "local_path": str(caption_path),
                    "storage_uri": str(caption_path),
                    "public_path": f"/media/prj_subschool/{suffix}/captions.vtt",
                },
            )
            caption_asset_id = caption_asset.id
            asset = repo.add(
                kind="media_asset",
                organization_id="org_demo",
                project_id="prj_subschool",
                status="ready",
                data={
                    "type": "video",
                    "local_path": str(video_path),
                    "storage_uri": str(video_path),
                    "public_path": f"/media/prj_subschool/{suffix}/video.mp4",
                    "checksum": "test-video-checksum",
                },
            )
        else:
            asset = repo.add(
                kind="media_asset",
                organization_id="org_demo",
                project_id="prj_subschool",
                status="ready",
                data={"type": "video", "local_path": "/not-needed-in-mock.mp4", "storage_uri": "mock"},
            )
        video = repo.add(
            kind="video",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="approved",
            data={"caption_asset_id": caption_asset_id, "versions": []},
        )
        version = repo.add(
            kind="video_version",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="approved",
            data={
                "video_id": video.id,
                "render_asset_id": asset.id,
                "checksum": "test-video-checksum",
                "aspect_ratio": "9:16",
            },
        )
        repo.update(video, data={"versions": [ResourceRepository.serialize(version)], "latest_version_id": version.id})
        return version.id


def test_confirm_is_idempotent_and_schedules_metrics_once(client, auth_headers) -> None:
    version_id = _approved_version()
    prepared = client.post(
        "/v1/publications",
        json={
            "video_version_id": version_id,
            "connection_id": "conn_youtube_demo",
            "platform": "youtube",
            "title": "Idempotent publication",
            "privacy": "private",
        },
        headers=auth_headers,
    )
    assert prepared.status_code == 202
    publication_id = prepared.json()["publication_id"]
    payload = {"confirmation_token": prepared.json()["confirmation_token"]}
    first = client.post(f"/v1/publications/{publication_id}/confirm", json=payload, headers=auth_headers)
    second = client.post(f"/v1/publications/{publication_id}/confirm", json=payload, headers=auth_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["external_post_id"] == second.json()["external_post_id"]
    checkpoints = client.get("/v1/projects/prj_subschool/metric-checkpoints", headers=auth_headers).json()["items"]
    own = [item for item in checkpoints if item["publication_id"] == publication_id]
    assert sorted(item["window"] for item in own) == ["24h", "7d"]


def test_provider_kill_switch_blocks_new_attempts(client, auth_headers) -> None:
    version_id = _approved_version()
    paused = client.post(
        "/v1/admin/providers/youtube/pause",
        json={"comment": "Safety drill"},
        headers=auth_headers,
    )
    assert paused.status_code == 200
    try:
        blocked = client.post(
            "/v1/publications",
            json={
                "video_version_id": version_id,
                "connection_id": "conn_youtube_demo",
                "platform": "youtube",
                "title": "Must stay blocked",
            },
            headers=auth_headers,
        )
        assert blocked.status_code == 423
    finally:
        resumed = client.post("/v1/admin/providers/youtube/resume", headers=auth_headers)
        assert resumed.status_code == 200


def test_export_fallback_contains_video_caption_thumbnail_and_manifest(client, auth_headers) -> None:
    version_id = _approved_version(with_media=True)
    prepared = client.post(
        "/v1/publications",
        json={
            "video_version_id": version_id,
            "connection_id": "unconfigured_export",
            "platform": "export",
            "title": "Complete export",
            "caption": "Ready to publish.",
            "hashtags": ["education", "subschool"],
        },
        headers=auth_headers,
    )
    assert prepared.status_code == 202
    publication_id = prepared.json()["publication_id"]
    confirmed = client.post(
        f"/v1/publications/{publication_id}/confirm",
        json={"confirmation_token": prepared.json()["confirmation_token"]},
        headers=auth_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "export_ready"
    downloaded = client.get(f"/v1/publications/{publication_id}/export", headers=auth_headers)
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as bundle:
        names = set(bundle.namelist())
        assert {"video.mp4", "captions.vtt", "thumbnail.jpg", "caption.txt", "hashtags.txt", "publication.json"} <= names
        assert bundle.read("caption.txt") == b"Ready to publish."


def test_youtube_status_normalization() -> None:
    youtube = MagicMock()
    youtube.videos.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "video_1",
                "status": {"uploadStatus": "processed", "privacyStatus": "private"},
                "contentDetails": {"duration": "PT31S"},
            }
        ]
    }
    settings = get_settings().model_copy(
        update={
            "youtube_client_id": "client",
            "youtube_client_secret": "secret",
            "youtube_refresh_token": "refresh",
        }
    )
    with patch("googleapiclient.discovery.build", return_value=youtube):
        status = get_youtube_video_status(settings, video_id="video_1", secret_ref=None)
    assert status["status"] == "published"
    assert status["provider_status"] == "processed"
    assert status["duration"] == "PT31S"


def test_score_override_is_reasoned_and_audited(client, auth_headers) -> None:
    with SessionLocal() as session:
        report = ResourceRepository(session).add(
            kind="score_report",
            organization_id="org_demo",
            project_id="prj_subschool",
            status="complete",
            data={"publish_readiness": 78, "predicted_performance": 62, "hard_gates_unchanged": True},
        )
        report_id = report.id
    missing_reason = client.post(
        f"/v1/score-reports/{report_id}/override",
        json={"score": "publish_readiness", "value": 84, "reason": "short"},
        headers=auth_headers,
    )
    assert missing_reason.status_code == 422
    changed = client.post(
        f"/v1/score-reports/{report_id}/override",
        json={
            "score": "predicted_performance",
            "value": 71,
            "reason": "Human reviewer has current campaign evidence.",
        },
        headers=auth_headers,
    )
    assert changed.status_code == 200
    assert changed.json()["score_report"]["effective_scores"]["predicted_performance"] == 71
    assert changed.json()["override"]["hard_gates_unchanged"] is True
    audit = client.get("/v1/projects/prj_subschool/audit-log", headers=auth_headers).json()["items"]
    assert any(item.get("event_type") == "score.overridden" and item.get("resource_id") == report_id for item in audit)


def test_project_score_thresholds_have_system_floors(client, auth_headers) -> None:
    blocked = client.patch(
        "/v1/projects/prj_subschool",
        json={"settings": {"scoring": {"readiness_autopublish": 20}}},
        headers=auth_headers,
    )
    assert blocked.status_code == 422
    accepted = client.patch(
        "/v1/projects/prj_subschool",
        json={"settings": {"scoring": {"readiness_autopublish": 90}}},
        headers=auth_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["settings"]["scoring"]["readiness_autopublish"] == 90
    assert "budget" in accepted.json()["settings"]


def test_webhook_crud_signed_delivery_history_and_replay(client, auth_headers) -> None:
    created = client.post(
        "/v1/projects/prj_subschool/webhooks",
        json={"url": "https://example.com/avs-events", "events": ["generation.completed"]},
        headers=auth_headers,
    )
    assert created.status_code == 201
    webhook_id = created.json()["id"]
    updated = client.patch(
        f"/v1/webhooks/{webhook_id}",
        json={"events": ["generation.completed", "publication.published"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    delivery = client.post(f"/v1/webhooks/{webhook_id}/test", headers=auth_headers)
    assert delivery.status_code == 200
    assert delivery.json()["status"] == "delivered"
    assert delivery.json()["signature"].startswith("sha256=")
    assert delivery.json()["event"]["timestamp"]
    replayed = client.post(
        f"/v1/webhook-deliveries/{delivery.json()['id']}/replay",
        headers=auth_headers,
    )
    assert replayed.status_code == 200
    assert replayed.json()["attempt"] == 2
    assert replayed.json()["event_id"] == delivery.json()["event_id"]
    history = client.get(f"/v1/webhooks/{webhook_id}/deliveries", headers=auth_headers)
    assert any(item["id"] == delivery.json()["id"] for item in history.json()["items"])
    deleted = client.delete(f"/v1/webhooks/{webhook_id}", headers=auth_headers)
    assert deleted.status_code == 204
