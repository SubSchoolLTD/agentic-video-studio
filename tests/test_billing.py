from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from apps.api.app.billing import (
    charge_feature,
    estimate_veo_billable_seconds,
    outstanding_charge_cents,
    project_budget_snapshot,
    refund_feature_charges,
    settle_feature_charge,
)
from apps.api.app.database import SessionLocal
from apps.api.app.models import CreditLedger, Resource, Wallet


def test_continuous_scene_quote_reserves_for_role_specific_roots() -> None:
    assert estimate_veo_billable_seconds(
        target_duration_seconds=30,
        scene_count_min=4,
        scene_count_max=6,
        scene_count_flex=2,
        continuous_scenes=True,
    ) == 34


def test_continuous_scene_quote_supports_longer_rolling_timelines() -> None:
    billable_seconds = estimate_veo_billable_seconds(
        target_duration_seconds=3_600,
        scene_count_min=5,
        scene_count_max=8,
        scene_count_flex=2,
        continuous_scenes=True,
    )

    assert billable_seconds >= 3_600


def test_failed_feature_charge_is_refunded_once(client) -> None:
    organization_id = f"org_refund_{uuid4().hex[:12]}"
    reference_id = f"job_refund_{uuid4().hex[:12]}"
    with SessionLocal() as session:
        session.add(Wallet(organization_id=organization_id, balance_cents=1_000))
        session.commit()
        charge_feature(
            session,
            organization_id=organization_id,
            user_id="usr_refund_test",
            feature_key="video.generate",
            quantity=10,
            reference_id=reference_id,
        )
        assert session.get(Wallet, organization_id).balance_cents == 760
        assert outstanding_charge_cents(session, organization_id, reference_id) == 240

        first = refund_feature_charges(
            session,
            organization_id=organization_id,
            reference_id=reference_id,
            reason="Provider failed before a usable result",
        )
        second = refund_feature_charges(
            session,
            organization_id=organization_id,
            reference_id=reference_id,
            reason="Duplicate failure callback",
        )

        assert len(first) == 1
        assert second == []
        assert session.get(Wallet, organization_id).balance_cents == 1_000
        assert outstanding_charge_cents(session, organization_id, reference_id) == 0
        ledger = list(
            session.scalars(
                select(CreditLedger).where(
                    CreditLedger.organization_id == organization_id,
                    CreditLedger.reference_id == reference_id,
                )
            )
        )
        assert sorted((item.event_type, int(item.amount_cents)) for item in ledger) == [
            ("ai_usage", -240),
            ("ai_usage_refund", 240),
        ]


def test_successful_feature_charge_is_settled_to_actual_provider_units(client) -> None:
    organization_id = f"org_settle_{uuid4().hex[:12]}"
    reference_id = f"job_settle_{uuid4().hex[:12]}"
    with SessionLocal() as session:
        session.add(Wallet(organization_id=organization_id, balance_cents=5_000))
        session.commit()
        charge_feature(
            session,
            organization_id=organization_id,
            user_id="usr_settle_test",
            feature_key="video.generate",
            quantity=42,
            reference_id=reference_id,
        )

        settled = settle_feature_charge(
            session,
            organization_id=organization_id,
            reference_id=reference_id,
            actual_quantity=30,
        )
        repeated = settle_feature_charge(
            session,
            organization_id=organization_id,
            reference_id=reference_id,
            actual_quantity=30,
        )

        assert settled == {
            "actual_quantity": 30,
            "customer_charge_cents": 720,
            "provider_cost_usd": 6.0,
            "refunded_cents": 288,
            "absorbed_customer_charge_cents": 0,
        }
        assert repeated["refunded_cents"] == 0
        assert repeated["customer_charge_cents"] == 720
        assert session.get(Wallet, organization_id).balance_cents == 4_280
        assert outstanding_charge_cents(session, organization_id, reference_id) == 720
        charges = list(
            session.scalars(
                select(CreditLedger).where(
                    CreditLedger.organization_id == organization_id,
                    CreditLedger.reference_id == reference_id,
                    CreditLedger.event_type == "ai_usage",
                )
            )
        )
        assert len(charges) == 1
        assert float(charges[0].monetary_amount_usd or 0) == 6.0


def test_monthly_project_budget_uses_net_ledger_spend_and_blocks_overage(client) -> None:
    organization_id = f"org_budget_{uuid4().hex[:12]}"
    project_id = f"prj_budget_{uuid4().hex[:12]}"
    first_job_id = f"job_budget_{uuid4().hex[:12]}"
    second_job_id = f"job_budget_{uuid4().hex[:12]}"
    with SessionLocal() as session:
        project = Resource(
            id=project_id,
            organization_id=organization_id,
            project_id=project_id,
            kind="project",
            status="active",
            data={"timezone": "UTC", "settings": {"budget": {"monthly_usd": 5}}},
        )
        first_job = Resource(
            id=first_job_id,
            organization_id=organization_id,
            project_id=project_id,
            kind="generation_job",
            status="queued",
            data={},
        )
        second_job = Resource(
            id=second_job_id,
            organization_id=organization_id,
            project_id=project_id,
            kind="generation_job",
            status="queued",
            data={},
        )
        session.add_all([project, first_job, second_job, Wallet(organization_id=organization_id, balance_cents=10_000)])
        session.commit()

        # Deposits never count as monthly usage.
        charge_feature(
            session,
            organization_id=organization_id,
            user_id="usr_budget_test",
            feature_key="video.generate",
            quantity=10,
            reference_id=first_job_id,
        )
        snapshot = project_budget_snapshot(session, project=project)
        assert snapshot["spent_cents"] == 240
        assert snapshot["remaining_cents"] == 260
        assert snapshot["percent_used"] == pytest.approx(0.48)

        with pytest.raises(HTTPException) as blocked:
            charge_feature(
                session,
                organization_id=organization_id,
                user_id="usr_budget_test",
                feature_key="video.generate",
                quantity=11,
                reference_id=second_job_id,
            )
        assert blocked.value.status_code == 402
        assert blocked.value.detail["code"] == "monthly_budget_exceeded"
        assert blocked.value.detail["remaining_cents"] == 260

        refund_feature_charges(
            session,
            organization_id=organization_id,
            reference_id=first_job_id,
            reason="No usable result",
        )
        refreshed_project = session.get(Resource, project_id)
        refunded = project_budget_snapshot(session, project=refreshed_project)
        assert refunded["spent_cents"] == 0
        assert refunded["remaining_cents"] == 500

        charge_feature(
            session,
            organization_id=organization_id,
            user_id="usr_budget_test",
            feature_key="video.generate",
            quantity=11,
            reference_id=second_job_id,
        )
