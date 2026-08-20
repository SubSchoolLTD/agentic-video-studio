from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from apps.api.app.billing import (
    charge_feature,
    outstanding_charge_cents,
    refund_feature_charges,
    settle_feature_charge,
)
from apps.api.app.database import SessionLocal
from apps.api.app.models import CreditLedger, Wallet


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
