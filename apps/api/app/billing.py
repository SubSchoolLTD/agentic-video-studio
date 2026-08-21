from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CreditLedger, PriceRule, PromoCode, PromoRedemption, Wallet


def _customer_cents(provider_cost_usd: str) -> int:
    return int(
        (Decimal(provider_cost_usd) * Decimal("1.20") * 100).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )


DEFAULT_PRICES = (
    {
        "feature_key": "project.website_analysis",
        "label": "Website and brand analysis",
        "unit": "analysis",
        "provider": "Parallel + Google",
        "integration": "Parallel Search / Vertex AI",
        "model_id": "Parallel Search + gemini-2.5-flash",
        "provider_cost_per_unit_usd": Decimal("0.02"),
        "charge_cents": _customer_cents("0.02"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "research.run",
        "label": "Agentic web research",
        "unit": "research run",
        "provider": "Parallel",
        "integration": "Parallel Search API",
        "model_id": "search",
        "provider_cost_per_unit_usd": Decimal("0.05"),
        "charge_cents": _customer_cents("0.05"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "video.generate",
        "label": "Creator-led video with voiceover",
        "unit": "generated second per aspect ratio",
        "provider": "Google + Parallel",
        "integration": "Veo / Gemini / Cloud TTS / Parallel",
        "model_id": "veo-3.1-generate-001 + gemini-2.5-flash + Chirp 3 HD",
        "provider_cost_per_unit_usd": Decimal("0.20"),
        "charge_cents": _customer_cents("0.20"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "video.generate_native_audio",
        "label": "UGC video with native Veo speech",
        "unit": "generated second per aspect ratio",
        "provider": "Google + Parallel",
        "integration": "Veo native audio / Gemini / Parallel",
        "model_id": "veo-3.1-generate-001 + gemini-2.5-flash",
        "provider_cost_per_unit_usd": Decimal("0.40"),
        "charge_cents": _customer_cents("0.40"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "video.scene_regenerate",
        "label": "AI scene regeneration",
        "unit": "generated second",
        "provider": "Google",
        "integration": "Vertex AI Veo",
        "model_id": "veo-3.1-generate-001",
        "provider_cost_per_unit_usd": Decimal("0.20"),
        "charge_cents": _customer_cents("0.20"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "video.scene_regenerate_native_audio",
        "label": "Native-audio scene regeneration",
        "unit": "generated second",
        "provider": "Google",
        "integration": "Vertex AI Veo native audio",
        "model_id": "veo-3.1-generate-001",
        "provider_cost_per_unit_usd": Decimal("0.40"),
        "charge_cents": _customer_cents("0.40"),
        "margin_percent": Decimal("20.00"),
    },
    {
        "feature_key": "character.generate",
        "label": "AI creator character",
        "unit": "reference image",
        "provider": "Google",
        "integration": "Vertex AI Gemini Image",
        "model_id": "gemini-2.5-flash-image",
        "provider_cost_per_unit_usd": Decimal("0.04"),
        "charge_cents": _customer_cents("0.04"),
        "margin_percent": Decimal("20.00"),
    },
)


def seed_price_rules(session: Session) -> None:
    for price in DEFAULT_PRICES:
        rule = session.get(PriceRule, price["feature_key"])
        if not rule:
            session.add(PriceRule(**price))
            continue
        # Keep administrator-controlled economics, but refresh provider provenance.
        rule.provider = str(price["provider"])
        rule.integration = str(price["integration"])
        rule.model_id = str(price["model_id"])
        session.add(rule)
    session.commit()


def ensure_wallet(session: Session, organization_id: str, *, commit: bool = True) -> Wallet:
    wallet = session.get(Wallet, organization_id)
    if not wallet:
        wallet = Wallet(organization_id=organization_id, balance_cents=0)
        session.add(wallet)
        if commit:
            session.commit()
            session.refresh(wallet)
        else:
            session.flush()
    return wallet


def add_ledger_entry(
    session: Session,
    *,
    organization_id: str,
    amount_cents: int,
    event_type: str,
    description: str,
    user_id: str | None = None,
    feature_key: str | None = None,
    reference_id: str | None = None,
    monetary_amount_usd: float | None = None,
    metadata: dict[str, Any] | None = None,
    allow_negative_balance: bool = False,
    commit: bool = True,
) -> CreditLedger:
    wallet = session.scalar(
        select(Wallet).where(Wallet.organization_id == organization_id).with_for_update()
    )
    if not wallet:
        wallet = Wallet(organization_id=organization_id, balance_cents=0)
        session.add(wallet)
        session.flush()
    next_balance = int(wallet.balance_cents) + int(amount_cents)
    if next_balance < 0 and not allow_negative_balance:
        raise HTTPException(
            402,
            {
                "code": "insufficient_balance",
                "message": "Not enough balance for this action",
                "required_cents": abs(int(amount_cents)),
                "available_cents": int(wallet.balance_cents),
                "shortfall_cents": abs(next_balance),
                "currency": "USD",
            },
        )
    wallet.balance_cents = next_balance
    entry = CreditLedger(
        id=f"led_{secrets.token_hex(12)}",
        organization_id=organization_id,
        user_id=user_id,
        amount_cents=int(amount_cents),
        event_type=event_type,
        feature_key=feature_key,
        reference_id=reference_id,
        monetary_amount_usd=monetary_amount_usd,
        description=description[:300],
        metadata_json=metadata or {},
    )
    session.add_all([wallet, entry])
    if commit:
        session.commit()
        session.refresh(entry)
    else:
        session.flush()
    return entry


def feature_price(session: Session, feature_key: str) -> PriceRule:
    rule = session.get(PriceRule, feature_key)
    if not rule or not rule.is_active:
        raise HTTPException(503, f"Pricing is not configured for {feature_key}")
    return rule


def quote_feature(session: Session, feature_key: str, quantity: int = 1) -> dict[str, Any]:
    rule = feature_price(session, feature_key)
    normalized_quantity = max(1, int(quantity))
    provider_cost = (Decimal(str(rule.provider_cost_per_unit_usd)) * normalized_quantity).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    charge_cents = int(rule.charge_cents) * normalized_quantity
    return {
        "feature_key": feature_key,
        "quantity": normalized_quantity,
        "unit": rule.unit,
        "charge_cents": charge_cents,
        "charge_usd": round(charge_cents / 100, 2),
        "provider_cost_usd": float(provider_cost),
    }


def charge_feature(
    session: Session,
    *,
    organization_id: str,
    user_id: str,
    feature_key: str,
    quantity: int,
    reference_id: str | None,
) -> CreditLedger:
    rule = feature_price(session, feature_key)
    quote = quote_feature(session, feature_key, quantity)
    return add_ledger_entry(
        session,
        organization_id=organization_id,
        user_id=user_id,
        amount_cents=-int(quote["charge_cents"]),
        event_type="ai_usage",
        feature_key=feature_key,
        reference_id=reference_id,
        monetary_amount_usd=float(quote["provider_cost_usd"]),
        description=f"{rule.label} × {quote['quantity']}",
        metadata={
            "unit_charge_cents": int(rule.charge_cents),
            "quantity": quote["quantity"],
            "configured_provider_cost_usd": quote["provider_cost_usd"],
            "cost_basis": "admin_price_rule",
            "currency": "USD",
        },
    )


def veo_request_duration(seconds: float) -> int:
    return next((value for value in (4, 6, 8) if seconds <= value), 8)


def estimate_veo_billable_seconds(
    *,
    target_duration_seconds: int,
    scene_count_min: int,
    scene_count_max: int,
    scene_count_flex: int,
) -> int:
    """Reserve for the most expensive allowed scene split after Veo's 4/6/8-second rounding."""
    allowed_min = max(2, scene_count_min - scene_count_flex)
    allowed_max = min(20, scene_count_max + scene_count_flex)
    totals = [
        scene_count * veo_request_duration(target_duration_seconds / scene_count)
        for scene_count in range(allowed_min, allowed_max + 1)
    ]
    return max(totals or [veo_request_duration(target_duration_seconds)])


def outstanding_charge_cents(session: Session, organization_id: str, reference_id: str) -> int:
    entries = list(
        session.scalars(
            select(CreditLedger).where(
                CreditLedger.organization_id == organization_id,
                CreditLedger.reference_id == reference_id,
                CreditLedger.event_type.in_(("ai_usage", "ai_usage_refund")),
            )
        )
    )
    return max(0, -sum(int(item.amount_cents) for item in entries))


def refund_feature_charges(
    session: Session,
    *,
    organization_id: str,
    reference_id: str,
    reason: str,
) -> list[CreditLedger]:
    """Idempotently return reserved dollars when no usable result was produced."""
    charges = list(
        session.scalars(
            select(CreditLedger)
            .where(
                CreditLedger.organization_id == organization_id,
                CreditLedger.reference_id == reference_id,
                CreditLedger.event_type == "ai_usage",
            )
            .order_by(CreditLedger.created_at)
        )
    )
    if not charges:
        return []
    wallet = session.scalar(select(Wallet).where(Wallet.organization_id == organization_id).with_for_update())
    if not wallet:
        wallet = Wallet(organization_id=organization_id, balance_cents=0)
        session.add(wallet)
        session.flush()
    refunds: list[CreditLedger] = []
    for charge in charges:
        refund_id = f"led_ref_{hashlib.sha256(charge.id.encode()).hexdigest()[:24]}"
        if session.get(CreditLedger, refund_id):
            continue
        amount = abs(int(charge.amount_cents))
        wallet.balance_cents = int(wallet.balance_cents) + amount
        refund = CreditLedger(
            id=refund_id,
            organization_id=organization_id,
            user_id=charge.user_id,
            amount_cents=amount,
            event_type="ai_usage_refund",
            feature_key=charge.feature_key,
            reference_id=reference_id,
            monetary_amount_usd=0,
            description=f"Refund: {charge.description}"[:300],
            metadata_json={"refunded_ledger_id": charge.id, "reason": reason[:200], "currency": "USD"},
        )
        session.add(refund)
        refunds.append(refund)
    if refunds:
        session.add(wallet)
        session.commit()
        for refund in refunds:
            session.refresh(refund)
    return refunds


def settle_feature_charge(
    session: Session,
    *,
    organization_id: str,
    reference_id: str,
    actual_quantity: int,
    reason: str = "Unused generation reserve",
) -> dict[str, Any]:
    """Reconcile a successful operation to provider-billable units.

    Generation reserves the most expensive allowed scene split before work starts.
    A successful render is charged only for the provider calls that actually ran.
    Automatic retries can make the real provider cost exceed the approved reserve;
    that overage is recorded for margin analytics but is absorbed by the platform.
    """
    charges = list(
        session.scalars(
            select(CreditLedger)
            .where(
                CreditLedger.organization_id == organization_id,
                CreditLedger.reference_id == reference_id,
                CreditLedger.event_type == "ai_usage",
            )
            .order_by(CreditLedger.created_at)
        )
    )
    if not charges:
        return {
            "actual_quantity": max(0, int(actual_quantity)),
            "customer_charge_cents": 0,
            "provider_cost_usd": 0.0,
            "refunded_cents": 0,
            "absorbed_customer_charge_cents": 0,
        }

    quantity = max(0, int(actual_quantity))
    feature_key = str(charges[-1].feature_key or "")
    rule = feature_price(session, feature_key)
    actual_customer_cents = int(rule.charge_cents) * quantity
    provider_cost = (Decimal(str(rule.provider_cost_per_unit_usd)) * quantity).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    authorized_cents = outstanding_charge_cents(session, organization_id, reference_id)
    customer_charge_cents = min(authorized_cents, actual_customer_cents)
    refund_cents = max(0, authorized_cents - customer_charge_cents)

    # Keep provider spend accurate at job level without counting it once per retry charge.
    for index, charge in enumerate(charges):
        charge.monetary_amount_usd = provider_cost if index == 0 else Decimal("0")
        charge.metadata_json = {
            **dict(charge.metadata_json or {}),
            "actual_quantity": quantity,
            "actual_provider_cost_usd": float(provider_cost),
            "settled": True,
            "cost_basis": "actual_provider_billable_units",
        }
        session.add(charge)

    if refund_cents:
        refund_id = f"led_set_{hashlib.sha256(reference_id.encode()).hexdigest()[:24]}"
        if not session.get(CreditLedger, refund_id):
            wallet = session.scalar(
                select(Wallet).where(Wallet.organization_id == organization_id).with_for_update()
            )
            if not wallet:
                wallet = Wallet(organization_id=organization_id, balance_cents=0)
                session.add(wallet)
                session.flush()
            wallet.balance_cents = int(wallet.balance_cents) + refund_cents
            session.add_all(
                [
                    wallet,
                    CreditLedger(
                        id=refund_id,
                        organization_id=organization_id,
                        user_id=charges[-1].user_id,
                        amount_cents=refund_cents,
                        event_type="ai_usage_refund",
                        feature_key=feature_key,
                        reference_id=reference_id,
                        monetary_amount_usd=0,
                        description=f"Settlement refund: {reason}"[:300],
                        metadata_json={
                            "actual_quantity": quantity,
                            "reserved_cents": authorized_cents,
                            "settled_charge_cents": customer_charge_cents,
                            "currency": "USD",
                        },
                    ),
                ]
            )
    session.commit()
    return {
        "actual_quantity": quantity,
        "customer_charge_cents": customer_charge_cents,
        "provider_cost_usd": float(provider_cost),
        "refunded_cents": refund_cents,
        "absorbed_customer_charge_cents": max(0, actual_customer_cents - authorized_cents),
    }


def hash_promo(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def promo_for_redemption(
    session: Session,
    *,
    raw_code: str,
    user_id: str,
    lock: bool = False,
) -> PromoCode:
    statement = select(PromoCode).where(PromoCode.code_hash == hash_promo(raw_code))
    if lock:
        statement = statement.with_for_update()
    promo = session.scalar(statement)
    ensure_promo_available(session, promo=promo, user_id=user_id)
    return promo


def ensure_promo_available(session: Session, *, promo: PromoCode, user_id: str) -> None:
    now = datetime.now(UTC)
    if not promo or not promo.is_active:
        raise HTTPException(404, "Promo code not found")
    expires = promo.expires_at
    if expires and (expires if expires.tzinfo else expires.replace(tzinfo=UTC)) <= now:
        raise HTTPException(410, "Promo code expired")
    if promo.max_redemptions is not None and promo.redemption_count >= promo.max_redemptions:
        raise HTTPException(409, "Promo code redemption limit reached")
    if session.scalar(
        select(PromoRedemption).where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    ):
        raise HTTPException(409, "Promo code already used by this account")


def dollars(cents: int) -> float:
    return round(int(cents) / 100, 2)
