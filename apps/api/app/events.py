from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import Settings
from .repository import ResourceRepository

logger = logging.getLogger("avs.events")


class EventSink:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def emit(
        self,
        session: Session,
        *,
        organization_id: str,
        project_id: str | None,
        event_type: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "event_id": ResourceRepository.new_id("evt"),
            "event_type": event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "correlation_id": correlation_id,
            "payload": payload or {},
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        ResourceRepository(session).add(
            kind="audit_event",
            organization_id=organization_id,
            project_id=project_id,
            resource_id=envelope["event_id"],
            status="recorded",
            data=envelope,
        )
        logger.info("domain_event", extra={"event": envelope})
        if self.settings.clickhouse_url:
            await self._send_clickhouse(envelope)
        if self.settings.google_pubsub_topic:
            await asyncio.to_thread(self._send_pubsub, envelope)
        return envelope

    def _send_pubsub(self, envelope: dict[str, Any]) -> None:
        try:
            from google.cloud import pubsub_v1

            publisher = pubsub_v1.PublisherClient()
            topic = self.settings.google_pubsub_topic
            topic_path = (
                topic
                if topic.startswith("projects/")
                else publisher.topic_path(self.settings.google_cloud_project, topic)
            )
            publisher.publish(
                topic_path,
                json.dumps(envelope, default=str).encode("utf-8"),
                event_type=envelope["event_type"],
                organization_id=envelope["organization_id"],
                project_id=envelope.get("project_id") or "",
            ).result(timeout=5)
        except Exception:
            logger.exception("pubsub_event_delivery_failed", extra={"event_id": envelope["event_id"]})

    async def _send_clickhouse(self, envelope: dict[str, Any]) -> None:
        query = (
            "INSERT INTO events_v1 FORMAT JSONEachRow"
        )
        row = {
            "organization_id": envelope["organization_id"],
            "project_id": envelope.get("project_id") or "00000000-0000-0000-0000-000000000000",
            "event_id": envelope["event_id"],
            "event_type": envelope["event_type"],
            "resource_type": envelope["resource_type"],
            "resource_id": envelope["resource_id"],
            "actor_type": "system",
            "payload_json": json.dumps(envelope["payload"], default=str),
            "occurred_at": envelope["occurred_at"],
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    self.settings.clickhouse_url,
                    params={"query": query, "date_time_input_format": "best_effort"},
                    headers={
                        "X-ClickHouse-User": self.settings.clickhouse_user,
                        "X-ClickHouse-Key": self.settings.clickhouse_password,
                    },
                    content=f"{json.dumps(row)}\n",
                )
                response.raise_for_status()
        except Exception:
            logger.exception("clickhouse_event_delivery_failed", extra={"event_id": envelope["event_id"]})

    async def emit_metric_snapshot(
        self,
        *,
        organization_id: str,
        project_id: str,
        publication_id: str,
        platform: str,
        account_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        """Append the normalized metric fact without making ClickHouse transactional state."""
        if not self.settings.clickhouse_url:
            return
        metrics = snapshot.get("metrics", {})
        row = {
            "organization_id": organization_id,
            "project_id": project_id,
            "publication_id": publication_id,
            "platform": platform,
            "account_id": account_id,
            "measurement_window": snapshot["window"],
            "post_age_seconds": int(snapshot["post_age_seconds"]),
            "views": metrics.get("views"),
            "engaged_views": metrics.get("engaged_views"),
            "likes": metrics.get("likes"),
            "comments": metrics.get("comments"),
            "shares": metrics.get("shares"),
            "watch_time_seconds": metrics.get("watch_time_seconds"),
            "average_view_duration_seconds": metrics.get("average_view_duration_seconds"),
            "average_view_percentage": metrics.get("average_view_percentage"),
            "subscribers_gained": metrics.get("subscribers_gained"),
            "subscribers_lost": metrics.get("subscribers_lost"),
            "raw_json": json.dumps(snapshot.get("raw_payload", {}), default=str),
            "captured_at": snapshot["captured_at"],
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    self.settings.clickhouse_url,
                    params={
                        "query": "INSERT INTO publication_metric_snapshots_v1 FORMAT JSONEachRow",
                        "date_time_input_format": "best_effort",
                    },
                    headers={
                        "X-ClickHouse-User": self.settings.clickhouse_user,
                        "X-ClickHouse-Key": self.settings.clickhouse_password,
                    },
                    content=f"{json.dumps(row)}\n",
                )
                response.raise_for_status()
        except Exception:
            logger.exception(
                "clickhouse_metric_delivery_failed",
                extra={"publication_id": publication_id, "window": snapshot.get("window")},
            )
