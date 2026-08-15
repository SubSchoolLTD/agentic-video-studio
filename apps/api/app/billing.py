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
    ("project.website_analysis", "Website and brand analysis", "analysis", Decimal("0.02"), 30, Decimal("66.67")),
    ("research.run", "Agentic web research", "research run", Decimal("0.05"), 75, Decimal("66.67")),
    ("video.generate", "AI video production", "rendered aspect ratio", Decimal("2.50"), 500, Decimal("50.00")),
    ("video.scene_regenerate", "AI scene regeneration", "scene", Decimal("0.50"), 100, Decimal("50.00")),
)


def seed_price_rules(session: Session) -> None:
    for key, label, unit, provider_cost, tokens, margin in DEFAULT_PRICES:
        if not session.get(PriceRule, key):
            session.add(
                PriceRule(
                    feature_key=key,
                    label=label,
                    unit=unit,
                    provider_cost_usd=provider_cost,
                    charge_tokens=tokens,
                    margin_percent=margin,
                )
            )
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
