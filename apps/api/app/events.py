from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Resource
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
        self._enqueue_webhooks(session, envelope)
        logger.info("domain_event", extra={"event": envelope})
        if self.settings.clickhouse_url:
            await self._send_clickhouse(envelope)
        if self.settings.google_pubsub_topic:
            await asyncio.to_thread(self._send_pubsub, envelope)
        return envelope

    def _enqueue_webhooks(self, session: Session, envelope: dict[str, Any]) -> None:
        if not envelope.get("project_id"):
            return
        webhooks = list(
            session.scalars(
                select(Resource).where(
                    Resource.kind == "webhook",
                    Resource.organization_id == envelope["organization_id"],
                    Resource.project_id == envelope["project_id"],
                    Resource.status == "active",
                )
            )
        )
        event = {
            "event_id": envelope["event_id"],
            "type": envelope["event_type"],
            "timestamp": int(datetime.now(UTC).timestamp()),
            "project_id": envelope["project_id"],
            "resource_type": envelope["resource_type"],
            "resource_id": envelope["resource_id"],
            "correlation_id": envelope.get("correlation_id"),
            "data": envelope.get("payload") or {},
        }
        raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        signature = hmac.new(self.settings.webhook_signing_secret.encode(), raw, hashlib.sha256).hexdigest()
        repo = ResourceRepository(session)
        for webhook in webhooks:
            patterns = list(webhook.data.get("events") or [])
            if patterns and not any(fnmatch.fnmatch(envelope["event_type"], pattern) for pattern in patterns):
                continue
            repo.add(
                kind="webhook_delivery",
                organization_id=envelope["organization_id"],
                project_id=envelope["project_id"],
                status="retry_scheduled",
                data={
                    "webhook_id": webhook.id,
                    "event_id": event["event_id"],
                    "event": event,
                    "attempt": 0,
                    "signature": f"sha256={signature}",
                    "next_attempt_at": datetime.now(UTC).isoformat(),
                },
            )

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
            "correlation_id": envelope.get("correlation_id") or "",
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
