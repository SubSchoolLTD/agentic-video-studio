from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from .config import Settings

PROVIDER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "youtube": {
        "publish": True,
        "privacy": ["private", "unlisted", "public"],
        "schedule": True,
        "autopublish": True,
        "metrics": ["views", "engaged_views", "watch_time", "retention", "likes", "comments", "shares"],
        "requires_per_post_consent": False,
    },
    "instagram": {
        "publish": True,
        "schedule": False,
        "autopublish": False,
        "privacy": ["public"],
        "metrics": [],
        "connection_mode": "playwright_web",
        "requires_per_post_consent": True,
    },
    "tiktok": {
        "publish": True,
        "schedule": False,
        "autopublish": False,
        "privacy": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"],
        "connection_mode": "playwright_web",
        "requires_per_post_consent": True,
        "requires_manual_privacy_choice": True,
    },
    # Internal download capability. It is intentionally not exposed as a connector.
    "export": {
        "publish": False,
        "schedule": False,
        "autopublish": False,
        "fallback": "download_package",
    },
}


def youtube_authorization_url(settings: Settings, *, state: str) -> tuple[str, str]:
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise RuntimeError("YouTube OAuth client is not configured")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.youtube_redirect_uri],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        state=state,
    )
    flow.redirect_uri = settings.youtube_redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, str(flow.code_verifier or "")


def exchange_youtube_code(
    settings: Settings,
    *,
    code: str,
    state: str,
    code_verifier: str,
) -> dict[str, Any]:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.youtube_redirect_uri],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = settings.youtube_redirect_uri
    flow.fetch_token(code=code)
    credentials = flow.credentials
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "scopes": list(credentials.scopes or []),
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
    }


def _store_json_secret(
    settings: Settings,
    *,
    secret_name: str,
    local_name: str,
    payload: dict[str, Any],
) -> str:
    if settings.google_cloud_project and settings.app_env not in {"local", "test"}:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{settings.google_cloud_project}/secrets/{secret_name}"
        version = client.add_secret_version(
            request={"parent": parent, "payload": {"data": json.dumps(payload).encode("utf-8")}}
        )
        return f"gcp:{version.name}"
    secret_dir = settings.storage_root.parent / ".secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secret_dir / f"{local_name}.json"
    secret_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    secret_path.chmod(0o600)
    return f"local:{secret_path}"


def store_oauth_secret(settings: Settings, connection_id: str, payload: dict[str, Any]) -> str:
    return _store_json_secret(
        settings,
        secret_name=settings.youtube_refresh_token_secret,
        local_name=connection_id,
        payload=payload,
    )


def load_oauth_secret(secret_ref: str | None) -> dict[str, Any]:
    if not secret_ref:
        return {}
    if secret_ref.startswith("local:"):
        return json.loads(Path(secret_ref.removeprefix("local:")).read_text(encoding="utf-8"))
    if secret_ref.startswith("gcp:"):
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_ref.removeprefix("gcp:")})
        return json.loads(response.payload.data.decode("utf-8"))
    legacy_path = Path(secret_ref)
    if legacy_path.is_file():
        return json.loads(legacy_path.read_text(encoding="utf-8"))
    return {}


def destroy_stored_secret(secret_ref: str | None) -> None:
    if not secret_ref:
        return
    if secret_ref.startswith("local:"):
        path = Path(secret_ref.removeprefix("local:"))
        if path.is_file():
            path.unlink()
        return
    if secret_ref.startswith("gcp:"):
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        client.destroy_secret_version(request={"name": secret_ref.removeprefix("gcp:")})


def load_refresh_token(settings: Settings, secret_ref: str | None) -> str:
    if settings.youtube_refresh_token:
        return settings.youtube_refresh_token
    return str(load_oauth_secret(secret_ref).get("refresh_token") or "")


def resolve_youtube_channel(settings: Settings, token_data: dict[str, Any]) -> dict[str, Any]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        scopes=token_data.get("scopes"),
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = youtube.channels().list(part="id,snippet,status", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("The selected Google identity has no accessible YouTube channel")
    channel = items[0]
    return {
        "id": channel["id"],
        "title": channel.get("snippet", {}).get("title") or "Connected YouTube channel",
        "privacy_status": channel.get("status", {}).get("privacyStatus"),
        "raw": channel,
    }


def upload_youtube_video(
    settings: Settings,
    *,
    file_path: Path,
    title: str,
    description: str,
    privacy: str,
    tags: list[str],
    made_for_kids: bool,
    contains_synthetic_media: bool,
    publish_at: str | None,
    secret_ref: str | None,
) -> dict[str, Any]:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    refresh_token = load_refresh_token(settings, secret_ref)
    if not refresh_token:
        raise RuntimeError("YouTube refresh token is unavailable")
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    body: dict[str, Any] = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "27"},
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at
        body["status"]["privacyStatus"] = "private"
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(file_path), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return {
        "external_post_id": response["id"],
        "external_url": f"https://youtu.be/{response['id']}",
        "raw": response,
    }


def get_youtube_video_status(
    settings: Settings,
    *,
    video_id: str,
    secret_ref: str | None,
) -> dict[str, Any]:
    """Resolve the provider-side processing state before any retry decision."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    refresh_token = load_refresh_token(settings, secret_ref)
    if not refresh_token:
        raise RuntimeError("YouTube refresh token is unavailable")
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = youtube.videos().list(part="status,snippet,contentDetails", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        return {
            "provider_status": "not_found",
            "status": "rejected",
            "rejection_reason": "Provider video was not found",
            "raw": response,
        }
    item = items[0]
    provider_status = str(item.get("status", {}).get("uploadStatus") or "uploaded")
    normalized = {
        "processed": "published",
        "uploaded": "processing",
        "failed": "retryable_failure",
        "rejected": "rejected",
        "deleted": "rejected",
    }.get(provider_status, "processing")
    return {
        "provider_status": provider_status,
        "status": normalized,
        "privacy_status": item.get("status", {}).get("privacyStatus"),
        "rejection_reason": item.get("status", {}).get("rejectionReason"),
        "failure_reason": item.get("status", {}).get("failureReason"),
        "duration": item.get("contentDetails", {}).get("duration"),
        "raw": item,
    }


def create_export_package(
    *,
    video_path: Path,
    captions_path: Path | None,
    output_path: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Create a provider-neutral, reproducible handoff bundle."""
    import hashlib

    output_path.parent.mkdir(parents=True, exist_ok=True)
    thumbnail_path = output_path.with_suffix(".thumbnail.jpg")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        completed = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(thumbnail_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            thumbnail_path.unlink(missing_ok=True)

    manifest = {
        "schema_version": "1.0",
        **metadata,
        "files": {
            "video": "video.mp4",
            "captions": "captions.vtt" if captions_path else None,
            "thumbnail": "thumbnail.jpg" if thumbnail_path.exists() else None,
            "caption": "caption.txt",
            "hashtags": "hashtags.txt",
        },
    }
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(video_path, "video.mp4")
        if captions_path and captions_path.exists():
            bundle.write(captions_path, "captions.vtt")
        if thumbnail_path.exists():
            bundle.write(thumbnail_path, "thumbnail.jpg")
        bundle.writestr("caption.txt", str(metadata.get("caption") or ""))
        bundle.writestr("hashtags.txt", " ".join(f"#{tag.lstrip('#')}" for tag in metadata.get("hashtags", [])))
        bundle.writestr("publication.json", json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    thumbnail_path.unlink(missing_ok=True)
    checksum = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return {"checksum": checksum, "size_bytes": output_path.stat().st_size, "manifest": manifest}


def confirmation_token() -> str:
    return secrets.token_urlsafe(24)
