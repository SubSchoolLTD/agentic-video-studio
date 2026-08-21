from __future__ import annotations

import json
import math
import secrets
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

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
        "schedule": True,
        "autopublish": False,
        "privacy": ["public"],
        "metrics": ["views", "reach", "likes", "comments", "shares", "saves"],
        "requires_professional_account": True,
    },
    "tiktok": {
        "publish": True,
        "schedule": False,
        "autopublish": False,
        "privacy": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"],
        "requires_creator_info": True,
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


def social_authorization_url(settings: Settings, *, provider: str, state: str) -> str:
    if provider == "instagram":
        if not settings.instagram_app_id or not settings.instagram_app_secret:
            raise RuntimeError("Instagram OAuth client is not configured")
        query = urlencode(
            {
                "client_id": settings.instagram_app_id,
                "redirect_uri": settings.instagram_redirect_uri,
                "response_type": "code",
                "scope": "instagram_business_basic,instagram_business_content_publish",
                "state": state,
                "enable_fb_login": "0",
                "force_authentication": "1",
            }
        )
        return f"https://www.instagram.com/oauth/authorize?{query}"
    if provider == "tiktok":
        if not settings.tiktok_client_key or not settings.tiktok_client_secret:
            raise RuntimeError("TikTok OAuth client is not configured")
        query = urlencode(
            {
                "client_key": settings.tiktok_client_key,
                "redirect_uri": settings.tiktok_redirect_uri,
                "response_type": "code",
                "scope": "user.info.basic,video.publish",
                "state": state,
            }
        )
        return f"https://www.tiktok.com/v2/auth/authorize/?{query}"
    raise ValueError(f"Unsupported OAuth provider: {provider}")


def exchange_social_code(settings: Settings, *, provider: str, code: str) -> dict[str, Any]:
    if provider == "instagram":
        response = httpx.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.instagram_app_id,
                "client_secret": settings.instagram_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": settings.instagram_redirect_uri,
                "code": code,
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        short_token = str(token_data.get("access_token") or "")
        if not short_token:
            raise RuntimeError("Instagram did not return an access token")
        long_lived = httpx.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.instagram_app_secret,
                "access_token": short_token,
            },
            timeout=30,
        )
        long_lived.raise_for_status()
        return _token_with_timing(
            {**token_data, **long_lived.json(), "provider": "instagram"}
        )
    if provider == "tiktok":
        response = httpx.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.tiktok_redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        if not token_data.get("access_token"):
            raise RuntimeError("TikTok did not return an access token")
        return _token_with_timing({**token_data, "provider": "tiktok"})
    raise ValueError(f"Unsupported OAuth provider: {provider}")


def _token_with_timing(payload: dict[str, Any]) -> dict[str, Any]:
    obtained_at = datetime.now(UTC)
    try:
        expires_in = max(0, int(payload.get("expires_in") or 0))
    except (TypeError, ValueError):
        expires_in = 0
    return {
        **payload,
        "obtained_at": obtained_at.isoformat(),
        "expires_at": (obtained_at + timedelta(seconds=expires_in)).isoformat()
        if expires_in
        else None,
    }


def social_token_needs_refresh(token_data: dict[str, Any], *, leeway_hours: int = 24) -> bool:
    raw_expiry = token_data.get("expires_at")
    if not raw_expiry:
        return False
    try:
        expiry = datetime.fromisoformat(str(raw_expiry))
    except ValueError:
        return True
    if not expiry.tzinfo:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= datetime.now(UTC) + timedelta(hours=leeway_hours)


def refresh_social_token(
    settings: Settings,
    *,
    provider: str,
    token_data: dict[str, Any],
) -> dict[str, Any]:
    if provider == "instagram":
        response = httpx.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token_data.get("access_token"),
            },
            timeout=30,
        )
        response.raise_for_status()
        return _token_with_timing({**token_data, **response.json(), "provider": provider})
    if provider == "tiktok":
        refresh_token = str(token_data.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("TikTok refresh token is unavailable")
        response = httpx.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        return _token_with_timing({**token_data, **response.json(), "provider": provider})
    raise ValueError(f"Unsupported OAuth provider: {provider}")


def resolve_social_account(settings: Settings, *, provider: str, token_data: dict[str, Any]) -> dict[str, Any]:
    access_token = str(token_data["access_token"])
    if provider == "instagram":
        response = httpx.get(
            f"https://graph.instagram.com/{settings.instagram_graph_version}/me",
            params={"fields": "user_id,username", "access_token": access_token},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "id": str(payload.get("user_id") or payload.get("id") or token_data.get("user_id") or ""),
            "display_name": str(payload.get("username") or "Connected Instagram account"),
        }
    response = httpx.post(
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json().get("data") or {}
    return {
        "id": str(token_data.get("open_id") or payload.get("creator_username") or ""),
        "display_name": str(payload.get("creator_nickname") or payload.get("creator_username") or "Connected TikTok account"),
        "creator_info": payload,
    }


def initiate_instagram_reel(
    settings: Settings,
    *,
    secret_ref: str,
    account_id: str,
    video_url: str,
    caption: str,
) -> dict[str, Any]:
    access_token = str(load_oauth_secret(secret_ref).get("access_token") or "")
    if not access_token:
        raise RuntimeError("Instagram access token is unavailable")
    response = httpx.post(
        f"https://graph.instagram.com/{settings.instagram_graph_version}/{account_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": access_token,
        },
        timeout=45,
    )
    response.raise_for_status()
    return {"container_id": str(response.json()["id"])}


def get_instagram_reel_status(settings: Settings, *, secret_ref: str, container_id: str) -> dict[str, Any]:
    access_token = str(load_oauth_secret(secret_ref).get("access_token") or "")
    response = httpx.get(
        f"https://graph.instagram.com/{settings.instagram_graph_version}/{container_id}",
        params={"fields": "status_code,status", "access_token": access_token},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def publish_instagram_reel(
    settings: Settings,
    *,
    secret_ref: str,
    account_id: str,
    container_id: str,
) -> dict[str, Any]:
    access_token = str(load_oauth_secret(secret_ref).get("access_token") or "")
    response = httpx.post(
        f"https://graph.instagram.com/{settings.instagram_graph_version}/{account_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token},
        timeout=45,
    )
    response.raise_for_status()
    return {"external_post_id": str(response.json()["id"])}


def initiate_tiktok_post(
    *,
    secret_ref: str,
    file_path: Path,
    title: str,
    privacy_level: str,
    allow_comments: bool,
    allow_duet: bool,
    allow_stitch: bool,
    synthetic_media_disclosure: bool,
) -> dict[str, Any]:
    access_token = str(load_oauth_secret(secret_ref).get("access_token") or "")
    if not access_token:
        raise RuntimeError("TikTok access token is unavailable")
    video_size = file_path.stat().st_size
    if video_size <= 0:
        raise RuntimeError("TikTok video file is empty")
    maximum_chunk_size = 64 * 1024 * 1024
    if video_size <= maximum_chunk_size:
        chunk_size = video_size
        total_chunk_count = 1
    else:
        total_chunk_count = math.ceil(video_size / maximum_chunk_size)
        chunk_size = video_size // total_chunk_count
    response = httpx.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": {
                "title": title,
                "privacy_level": privacy_level,
                "disable_comment": not allow_comments,
                "disable_duet": not allow_duet,
                "disable_stitch": not allow_stitch,
                "is_aigc": synthetic_media_disclosure,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            },
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error", {}).get("code") not in {None, "ok"}:
        raise RuntimeError(str(payload["error"].get("message") or "TikTok rejected the post"))
    data = payload.get("data") or {}
    publish_id = str(data.get("publish_id") or "")
    upload_url = str(data.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise RuntimeError("TikTok did not return an upload target")
    with file_path.open("rb") as source, httpx.Client(timeout=120) as client:
        for index in range(total_chunk_count):
            start = index * chunk_size
            chunk = source.read() if index == total_chunk_count - 1 else source.read(chunk_size)
            end = start + len(chunk) - 1
            upload = client.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{video_size}",
                },
                content=chunk,
            )
            upload.raise_for_status()
    return {"publish_id": publish_id}


def get_tiktok_post_status(*, secret_ref: str, publish_id: str) -> dict[str, Any]:
    access_token = str(load_oauth_secret(secret_ref).get("access_token") or "")
    response = httpx.post(
        "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={"publish_id": publish_id},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error", {}).get("code") not in {None, "ok"}:
        raise RuntimeError(str(payload["error"].get("message") or "TikTok status request failed"))
    return payload.get("data") or {}


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


def store_oauth_secret(settings: Settings, connection_id: str, payload: dict[str, Any]) -> str:
    if settings.google_cloud_project and settings.app_env not in {"local", "test"}:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = (
            f"projects/{settings.google_cloud_project}/secrets/"
            f"{settings.youtube_refresh_token_secret}"
        )
        version = client.add_secret_version(
            request={"parent": parent, "payload": {"data": json.dumps(payload).encode("utf-8")}}
        )
        return f"gcp:{version.name}"
    secret_dir = Path(".secrets")
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secret_dir / f"{connection_id}.json"
    secret_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    secret_path.chmod(0o600)
    return f"local:{secret_path}"


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
