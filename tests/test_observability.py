from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apps.api.app.billing import add_ledger_entry
from apps.api.app.database import SessionLocal
from apps.api.app.repository import ResourceRepository
from apps.api.app.routes import evaluate_operational_alerts


def test_all_required_grafana_dashboards_are_provisioned() -> None:
    dashboard_root = Path("infra/grafana/dashboards")
    dashboards = {json.loads(path.read_text())["uid"] for path in dashboard_root.glob("*.json")}
    assert {"avs-pipeline", "avs-ai", "avs-media", "avs-publishing", "avs-cost"} <= dashboards


def test_operational_alert_evaluator_detects_and_resolves_conditions(client, auth_headers) -> None:
    with SessionLocal() as session:
        repo = ResourceRepository(session)
        project = repo.add(
            kind="project",
            organization_id="org_demo",
            project_id=None,
            status="active",
            data={
                "name": "Alert fixture",
                "timezone": "UTC",
                "settings": {"budget": {"monthly_usd": 10}},
            },
        )
        project.project_id = project.id
        session.add(project)
        session.commit()
        add_ledger_entry(
            session,
            organization_id="org_demo",
            amount_cents=-1_100,
            event_type="ai_usage",
            description="Alert fixture usage",
            reference_id=project.id,
            allow_negative_balance=True,
        )
        checkpoint = repo.add(
            kind="metric_checkpoint",
            organization_id="org_demo",
            project_id=project.id,
            status="scheduled",
            data={
                "publication_id": "publication_alert_fixture",
                "window": "24h",
                "scheduled_at": (datetime.now(UTC) - timedelta(hours=3)).isoformat(),
            },
        )
        result = evaluate_operational_alerts(session)
        assert result["firing"] >= 2
        project_id = project.id
        checkpoint_id = checkpoint.id

    alerts = client.get("/v1/admin/alerts", headers=auth_headers)
    assert alerts.status_code == 200
    types = {item["alert_type"] for item in alerts.json()["items"]}
    assert {"budget_breach", "stale_metrics"} <= types

    with SessionLocal() as session:
        repo = ResourceRepository(session)
        project = repo.get_any(project_id, kind="project")
        checkpoint = repo.get_any(checkpoint_id, kind="metric_checkpoint")
        assert project and checkpoint
        add_ledger_entry(
            session,
            organization_id="org_demo",
            amount_cents=1_000,
            event_type="ai_usage_refund",
            description="Alert fixture refund",
            reference_id=project.id,
        )
        repo.update(checkpoint, status="complete")
        evaluate_operational_alerts(session)
    resolved = client.get("/v1/admin/alerts?status=resolved", headers=auth_headers)
    assert {"budget_breach", "stale_metrics"} <= {item["alert_type"] for item in resolved.json()["items"]}
