from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import CreditLedger, PriceRule, PromoCode, PromoRedemption, Subscription, Wallet

DEFAULT_PRICES = (
    {
        "feature_key": "project.website_analysis",
        "label": "Website and brand analysis",
        "unit": "analysis",
        "provider": "Parallel + Google",
        "integration": "Parallel Search / Vertex AI",
        "model_id": "Parallel Search + gemini-2.5-flash",
        "provider_cost_usd": Decimal("0.02"),
        "charge_tokens": 30,
        "margin_percent": Decimal("66.67"),
    },
    {
        "feature_key": "research.run",
        "label": "Agentic web research",
        "unit": "research run",
        "provider": "Parallel",
        "integration": "Parallel Search API",
        "model_id": "search",
        "provider_cost_usd": Decimal("0.05"),
        "charge_tokens": 75,
        "margin_percent": Decimal("66.67"),
    },
    {
        "feature_key": "video.generate",
        "label": "Creator-led video with voiceover",
        "unit": "rendered aspect ratio",
        "provider": "Google + Parallel",
        "integration": "Veo / Gemini / Cloud TTS / Parallel",
        "model_id": "veo-3.1-generate-001 + gemini-2.5-flash + Chirp 3 HD",
        "provider_cost_usd": Decimal("2.50"),
        "charge_tokens": 500,
        "margin_percent": Decimal("50.00"),
    },
    {
        "feature_key": "video.generate_native_audio",
        "label": "UGC video with native Veo speech",
        "unit": "rendered aspect ratio",
        "provider": "Google + Parallel",
        "integration": "Veo native audio / Gemini / Parallel",
        "model_id": "veo-3.1-generate-001 + gemini-2.5-flash",
        "provider_cost_usd": Decimal("4.00"),
        "charge_tokens": 800,
        "margin_percent": Decimal("50.00"),
    },
    {
        "feature_key": "video.scene_regenerate",
        "label": "AI scene regeneration",
        "unit": "scene",
        "provider": "Google",
        "integration": "Vertex AI Veo",
        "model_id": "veo-3.1-generate-001",
        "provider_cost_usd": Decimal("0.50"),
        "charge_tokens": 100,
        "margin_percent": Decimal("50.00"),
    },
    {
        "feature_key": "video.scene_regenerate_native_audio",
        "label": "Native-audio scene regeneration",
        "unit": "scene",
        "provider": "Google",
        "integration": "Vertex AI Veo native audio",
        "model_id": "veo-3.1-generate-001",
        "provider_cost_usd": Decimal("0.80"),
        "charge_tokens": 160,
        "margin_percent": Decimal("50.00"),
    },
    {
        "feature_key": "character.generate",
        "label": "AI creator character",
        "unit": "reference image",
        "provider": "Google",
        "integration": "Vertex AI Gemini Image",
        "model_id": "gemini-2.5-flash-image",
        "provider_cost_usd": Decimal("0.04"),
        "charge_tokens": 25,
        "margin_percent": Decimal("60.00"),
    },
)


def seed_price_rules(session: Session) -> None:
    for price in DEFAULT_PRICES:
        rule = session.get(PriceRule, price["feature_key"])
        if not rule:
            session.add(PriceRule(**price))
            continue
        # Schema provenance is safe to refresh while preserving all administrator-controlled economics.
        rule.provider = str(price["provider"])
        rule.integration = str(price["integration"])
        rule.model_id = str(price["model_id"])
        session.add(rule)
    session.commit()


def ensure_wallet(session: Session, organization_id: str) -> Wallet:
    wallet = session.get(Wallet, organization_id)
    if not wallet:
        wallet = Wallet(organization_id=organization_id, balance_tokens=0)
        session.add(wallet)
        session.commit()
        session.refresh(wallet)
    return wallet


def add_ledger_entry(
    session: Session,
    *,
    organization_id: str,
    amount_tokens: int,
    event_type: str,
    description: str,
    user_id: str | None = None,
    feature_key: str | None = None,
    reference_id: str | None = None,
    monetary_amount_usd: float | None = None,
    metadata: dict[str, Any] | None = None,
    allow_negative_balance: bool = False,
) -> CreditLedger:
    wallet = session.scalar(
        select(Wallet).where(Wallet.organization_id == organization_id).with_for_update()
    )
    if not wallet:
        wallet = Wallet(organization_id=organization_id, balance_tokens=0)
        session.add(wallet)
        session.flush()
    next_balance = int(wallet.balance_tokens) + int(amount_tokens)
    if next_balance < 0 and not allow_negative_balance:
        raise HTTPException(
            402,
            {
                "message": "Insufficient AI token balance",
                "required_tokens": abs(int(amount_tokens)),
                "available_tokens": int(wallet.balance_tokens),
            },
        )
    wallet.balance_tokens = next_balance
    entry = CreditLedger(
        id=f"led_{secrets.token_hex(12)}",
        organization_id=organization_id,
        user_id=user_id,
        amount_tokens=int(amount_tokens),
        event_type=event_type,
        feature_key=feature_key,
        reference_id=reference_id,
        monetary_amount_usd=monetary_amount_usd,
        description=description[:300],
        metadata_json=metadata or {},
    )
    session.add_all([wallet, entry])
    session.commit()
    session.refresh(entry)
    return entry


def grant_signup_credit(session: Session, organization_id: str, user_id: str, amount: int) -> None:
    exists = session.scalar(
        select(CreditLedger).where(
            CreditLedger.organization_id == organization_id,
            CreditLedger.event_type == "signup_credit",
        )
    )
    if not exists and amount > 0:
        add_ledger_entry(
            session,
            organization_id=organization_id,
            user_id=user_id,
            amount_tokens=amount,
            event_type="signup_credit",
            description="Welcome AI token credit",
            reference_id=user_id,
        )


def feature_price(session: Session, feature_key: str) -> PriceRule:
    rule = session.get(PriceRule, feature_key)
    if not rule or not rule.is_active:
        raise HTTPException(503, f"Pricing is not configured for {feature_key}")
    return rule


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
    normalized_quantity = max(1, int(quantity))
    amount = int(rule.charge_tokens) * normalized_quantity
    provider_cost = float(rule.provider_cost_usd) * normalized_quantity
    return add_ledger_entry(
        session,
        organization_id=organization_id,
        user_id=user_id,
        amount_tokens=-amount,
        event_type="ai_usage",
        feature_key=feature_key,
        reference_id=reference_id,
        monetary_amount_usd=provider_cost,
        description=f"{rule.label} × {normalized_quantity}",
        metadata={
            "unit_tokens": int(rule.charge_tokens),
            "quantity": normalized_quantity,
            "configured_provider_cost_usd": provider_cost,
            "cost_basis": "admin_price_rule",
        },
    )


def hash_promo(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def redeem_promo(
    session: Session,
    *,
    raw_code: str,
    user_id: str,
    organization_id: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    promo = session.scalar(select(PromoCode).where(PromoCode.code_hash == hash_promo(raw_code)).with_for_update())
    if not promo or not promo.is_active:
        raise HTTPException(404, "Promo code not found")
    expires = promo.expires_at
    if expires and (expires if expires.tzinfo else expires.replace(tzinfo=UTC)) <= now:
        raise HTTPException(410, "Promo code expired")
    if promo.max_redemptions is not None and promo.redemption_count >= promo.max_redemptions:
        raise HTTPException(409, "Promo code redemption limit reached")
    redemption = PromoRedemption(
        id=f"red_{secrets.token_hex(12)}",
        promo_code_id=promo.id,
        user_id=user_id,
        organization_id=organization_id,
    )
    session.add(redemption)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Promo code already redeemed by this account") from exc
    promo.redemption_count += 1
    if promo.credit_tokens:
        add_ledger_entry(
            session,
            organization_id=organization_id,
            user_id=user_id,
            amount_tokens=int(promo.credit_tokens),
            event_type="promo_credit",
            reference_id=promo.id,
            description="Promo code AI token credit",
        )
    if promo.subscription_days:
        subscription = session.get(Subscription, organization_id)
        current_expiry = None
        if subscription and subscription.expires_at:
            current_expiry = subscription.expires_at
            if current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=UTC)
        base = max(now, current_expiry or now)
        if not subscription:
            subscription = Subscription(organization_id=organization_id, starts_at=now)
        subscription.plan = "promo"
        subscription.status = "active"
        subscription.expires_at = base + timedelta(days=int(promo.subscription_days))
        session.add(subscription)
    session.add_all([promo, redemption])
    session.commit()
    wallet = ensure_wallet(session, organization_id)
    subscription = session.get(Subscription, organization_id)
    return {
        "status": "redeemed",
        "credit_tokens": int(promo.credit_tokens),
        "subscription_days": int(promo.subscription_days),
        "balance_tokens": int(wallet.balance_tokens),
        "subscription_expires_at": subscription.expires_at.isoformat() if subscription and subscription.expires_at else None,
    }
