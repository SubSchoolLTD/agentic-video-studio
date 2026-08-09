from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .publishing import load_refresh_token

YOUTUBE_ANALYTICS_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "likes,comments,shares,subscribersGained,subscribersLost"
)


def _number(value: str | int | float | None) -> int | float | None:
    if value is None:
        return None
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _availability(metrics: dict[str, Any], *, demo: bool = False) -> dict[str, str]:
    return {
        name: ("synthetic_demo" if demo and value is not None else "available" if value is not None else "unavailable")
        for name, value in metrics.items()
    }


def mock_youtube_metrics(*, window: str, published_at: datetime) -> dict[str, Any]:
    values = {
        "24h": {
            "views": 620,
            "engaged_views": 438,
            "likes": 38,
            "comments": 6,
            "shares": 11,
            "watch_time_seconds": 11_842,
            "average_view_duration_seconds": 19.1,
            "average_view_percentage": 63.7,
            "subscribers_gained": 3,
            "subscribers_lost": 0,
        },
        "7d": {
            "views": 4_210,
            "engaged_views": 3_074,
            "likes": 238,
            "comments": 31,
            "shares": 74,
            "watch_time_seconds": 82_516,
            "average_view_duration_seconds": 19.6,
            "average_view_percentage": 65.4,
            "subscribers_gained": 24,
            "subscribers_lost": 1,
        },
    }.get(window, {})
    captured_at = datetime.now(UTC)
    expected_age = {"24h": 24 * 3600, "7d": 7 * 24 * 3600}.get(window, 0)
    return {
        "window": window,
        "captured_at": captured_at.isoformat(),
        "post_age_seconds": max(expected_age, int((captured_at - published_at).total_seconds())),
        "metrics": values,
        "availability": _availability(values, demo=True),
        "provider_status": {"uploadStatus": "processed"},
        "raw_payload": {"demo_data": True, "window": window},
        "is_complete": True,
        "demo_data": True,
    }


def collect_youtube_metrics(
    settings: Settings,
    *,
    video_id: str,
    window: str,
    published_at: datetime,
    secret_ref: str | None,
) -> dict[str, Any]:
    """Collect public video statistics plus channel-scoped YouTube Analytics data."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    refresh_token = load_refresh_token(settings, secret_ref)
    if not refresh_token:
        raise RuntimeError("YouTube refresh token is unavailable")
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        scopes=scopes,
    )
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    public_payload = youtube.videos().list(part="statistics,status,contentDetails", id=video_id).execute()
    items = public_payload.get("items", [])
    if not items:
        raise RuntimeError("YouTube video was not found for the connected channel")
    item = items[0]
    statistics = item.get("statistics", {})
    metrics: dict[str, Any] = {
        "views": _number(statistics.get("viewCount")),
        "engaged_views": None,
        "likes": _number(statistics.get("likeCount")),
        "comments": _number(statistics.get("commentCount")),
        "shares": None,
        "watch_time_seconds": None,
        "average_view_duration_seconds": None,
        "average_view_percentage": None,
        "subscribers_gained": None,
        "subscribers_lost": None,
    }

    captured_at = datetime.now(UTC)
    # Analytics can lag and rejects future/current-day ranges, so a missing report is retained as missing.
    start_date = published_at.date()
    end_date = max(start_date, (captured_at - timedelta(days=1)).date())
    analytics_payload: dict[str, Any] | None = None
    analytics_error: str | None = None
    try:
        analytics = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
        analytics_payload = (
            analytics.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date.isoformat(),
                endDate=end_date.isoformat(),
                filters=f"video=={video_id}",
                dimensions="video",
                metrics=YOUTUBE_ANALYTICS_METRICS,
            )
            .execute()
        )
        rows = analytics_payload.get("rows") or []
        if rows:
            headers = [header["name"] for header in analytics_payload.get("columnHeaders", [])]
            values_by_name = dict(zip(headers, rows[0], strict=False))
            analytics_mapping = {
                "views": "views",
                "estimatedMinutesWatched": "watch_time_seconds",
                "averageViewDuration": "average_view_duration_seconds",
                "averageViewPercentage": "average_view_percentage",
                "likes": "likes",
                "comments": "comments",
                "shares": "shares",
                "subscribersGained": "subscribers_gained",
                "subscribersLost": "subscribers_lost",
            }
            for provider_name, metric_name in analytics_mapping.items():
                value = _number(values_by_name.get(provider_name))
                if provider_name == "estimatedMinutesWatched" and value is not None:
                    value = float(value) * 60
                if value is not None:
                    metrics[metric_name] = value
    except HttpError as exc:
        analytics_error = f"youtube_analytics_unavailable:{exc.resp.status}"

    return {
        "window": window,
        "captured_at": captured_at.isoformat(),
        "post_age_seconds": max(0, int((captured_at - published_at).total_seconds())),
        "metrics": metrics,
        "availability": _availability(metrics),
        "provider_status": item.get("status", {}),
        "raw_payload": {
            "youtube_data_api": public_payload,
            "youtube_analytics": analytics_payload,
            "youtube_analytics_error": analytics_error,
        },
        "is_complete": metrics["views"] is not None,
        "demo_data": False,
    }


def observed_performance(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative, explainable score until a >=10-item cohort exists."""
    metrics = snapshot.get("metrics", {})
    retention = metrics.get("average_view_percentage")
    views = metrics.get("views")
    interactions = sum(metrics.get(name) or 0 for name in ("likes", "comments", "shares"))
    engagement_rate = (interactions / views * 100) if views else None
    retention_component = min(100.0, float(retention) * 1.2) if retention is not None else 50.0
    engagement_component = min(100.0, engagement_rate * 10) if engagement_rate is not None else 50.0
    score = round(retention_component * 0.7 + engagement_component * 0.3)
    return {
        "observed_performance_index": score,
        "components": {
            "retention": round(retention_component, 1),
            "engagement": round(engagement_component, 1),
        },
        "engagement_rate_percent": round(engagement_rate, 2) if engagement_rate is not None else None,
        "confidence": 0.42,
        "cohort_size": 1,
        "caveat": "Low-confidence single-publication signal; correlation is not treated as causation.",
    }
