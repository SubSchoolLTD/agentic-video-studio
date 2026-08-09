from __future__ import annotations

import json
import secrets
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
        "publish": False,
        "schedule": True,
        "autopublish": False,
        "metrics": ["views", "reach", "likes", "comments", "shares", "saves"],
        "connection_limited": True,
        "fallback": "export",
    },
    "tiktok": {
        "publish": "interactive_or_draft",
        "schedule": False,
        "autopublish": False,
        "privacy": [],
        "requires_creator_info": True,
        "requires_per_post_consent": True,
        "requires_manual_privacy_choice": True,
        "fallback": "export",
    },
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


def store_oauth_secret(settings: Settings, connection_id: str, payload: dict[str, Any]) -> str:
    if settings.google_cloud_project and settings.app_env not in {"local", "test"}:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = (
            f"projects/{settings.google_cloud_project}/secrets/"
            f"{settings.youtube_refresh_token_secret}"
        )
        client.add_secret_version(
            request={"parent": parent, "payload": {"data": json.dumps(payload).encode("utf-8")}}
        )
        return f"gcp:{parent}/versions/latest"
    secret_dir = Path(".secrets")
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = secret_dir / f"{connection_id}.json"
    secret_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    secret_path.chmod(0o600)
    return str(secret_path)


def load_refresh_token(settings: Settings, secret_ref: str | None) -> str:
    if settings.youtube_refresh_token:
        return settings.youtube_refresh_token
    if secret_ref and secret_ref.startswith("local:"):
        payload = json.loads(Path(secret_ref.removeprefix("local:")).read_text(encoding="utf-8"))
        return str(payload.get("refresh_token") or "")
    if secret_ref and secret_ref.startswith("gcp:"):
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": secret_ref.removeprefix("gcp:")})
        payload = json.loads(response.payload.data.decode("utf-8"))
        return str(payload.get("refresh_token") or "")
    return ""


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


def confirmation_token() -> str:
    return secrets.token_urlsafe(24)
