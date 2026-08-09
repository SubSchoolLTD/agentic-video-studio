from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from apps.api.app.config import Settings
from apps.api.app.metrics import collect_youtube_metrics, observed_performance


def test_observed_performance_is_explicitly_low_confidence() -> None:
    report = observed_performance(
        {
            "metrics": {
                "views": 1_000,
                "likes": 50,
                "comments": 10,
                "shares": 10,
                "average_view_percentage": 62,
            }
        }
    )
    assert 0 <= report["observed_performance_index"] <= 100
    assert report["cohort_size"] == 1
    assert report["confidence"] < 0.5
    assert "correlation" in report["caveat"].lower()


def test_youtube_collector_preserves_unavailable_metrics() -> None:
    data_api = MagicMock()
    data_api.videos.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "statistics": {"viewCount": "321", "likeCount": "12"},
                "status": {"uploadStatus": "processed"},
            }
        ]
    }
    analytics_api = MagicMock()
    analytics_api.reports.return_value.query.return_value.execute.return_value = {
        "columnHeaders": [
            {"name": "video"},
            {"name": "views"},
            {"name": "averageViewPercentage"},
            {"name": "shares"},
        ],
        "rows": [["youtube_id", 321, 67.5, 4]],
    }
    settings = Settings(
        _env_file=None,
        youtube_client_id="client",
        youtube_client_secret="secret",
        youtube_refresh_token="refresh",
    )
    with (
        patch("googleapiclient.discovery.build", side_effect=[data_api, analytics_api]),
        patch("apps.api.app.metrics.load_refresh_token", return_value="refresh"),
    ):
        result = collect_youtube_metrics(
            settings,
            video_id="youtube_id",
            window="24h",
            published_at=datetime.now(UTC),
            secret_ref="gcp:secret",
        )
    assert result["metrics"]["views"] == 321
    assert result["metrics"]["average_view_percentage"] == 67.5
    assert result["metrics"]["shares"] == 4
    assert result["metrics"]["comments"] is None
    assert result["availability"]["comments"] == "unavailable"
    assert result["demo_data"] is False
