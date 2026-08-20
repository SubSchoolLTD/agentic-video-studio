from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .billing import (
    add_ledger_entry,
    dollars,
    ensure_promo_available,
    ensure_wallet,
    promo_bonus_cents,
    promo_for_topup,
)
from .config import Settings, get_settings
from .database import get_db
from .models import CreditLedger, PayPalTopup, PriceRule, PromoCode, PromoRedemption
from .paypal import PayPalClient, PayPalError, PayPalOrderState
from .security import Principal, get_principal

router = APIRouter(prefix="/v1/billing", tags=["billing"])
logger = logging.getLogger("avs.billing")


class TopupCreateRequest(BaseModel):
    amount_usd: Decimal = Field(ge=Decimal("12.00"), le=Decimal("100000.00"))
    promo_code: str | None = Field(default=None, min_length=3, max_length=64)

    @field_validator("amount_usd")
    @classmethod
    def two_decimal_places(cls, value: Decimal) -> Decimal:
        normalized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if value != normalized:
            raise ValueError("amount_usd supports at most two decimal places")
        return normalized


class TopupCaptureRequest(BaseModel):
    topup_id: str = Field(min_length=8, max_length=64)
    paypal_order_id: str = Field(min_length=8, max_length=64)


def _price(rule: PriceRule) -> dict[str, object]:
    return {
        "feature_key": rule.feature_key,
        "label": rule.label,
        "unit": rule.unit,
        "charge_cents": int(rule.charge_cents),
        "charge_usd": dollars(rule.charge_cents),
    }


@router.get("/public-pricing")
def public_pricing(
    session: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, object]:
    prices = list(
        session.scalars(select(PriceRule).where(PriceRule.is_active.is_(True)).order_by(PriceRule.label))
    )
    return {
        "currency": "USD",
        "minimum_topup_usd": settings.paypal_min_topup_usd,
        "prices": [_price(item) for item in prices],
    }


@router.get("/summary")
def billing_summary(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_db)
) -> dict[str, object]:
    wallet = ensure_wallet(session, principal.organization_id)
    prices = list(
        session.scalars(select(PriceRule).where(PriceRule.is_active.is_(True)).order_by(PriceRule.label))
    )
    return {
        "currency": "USD",
        "balance_cents": int(wallet.balance_cents),
        "balance_usd": dollars(wallet.balance_cents),
        "prices": [_price(item) for item in prices],
    }


@router.get("/ledger")
def billing_ledger(
    limit: int = 50,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    entries = list(
        session.scalars(
            select(CreditLedger)
            .where(CreditLedger.organization_id == principal.organization_id)
            .order_by(CreditLedger.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    )
    return {
        "currency": "USD",
        "items": [
            {
                "id": item.id,
                "amount_cents": int(item.amount_cents),
                "amount_usd": dollars(item.amount_cents),
                "event_type": item.event_type,
                "feature_key": item.feature_key,
                "reference_id": item.reference_id,
                "description": item.description,
                "provider_cost_usd": (
                    float(item.monetary_amount_usd) if item.monetary_amount_usd is not None else None
                ),
                "created_at": item.created_at.isoformat(),
            }
            for item in entries
        ],
    }


@router.get("/topups")
def topups(
    limit: int = 50,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    items = list(
        session.scalars(
            select(PayPalTopup)
            .where(PayPalTopup.organization_id == principal.organization_id)
            .order_by(PayPalTopup.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
    )
    return {
        "items": [
            {
                "id": item.id,
                "amount_usd": dollars(item.amount_cents),
                "bonus_usd": dollars(item.bonus_cents),
                "status": item.status,
                "paypal_order_id": item.paypal_order_id,
                "captured_at": item.captured_at.isoformat() if item.captured_at else None,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]
    }


@router.post("/topups/paypal", status_code=201)
def create_paypal_topup(
    payload: TopupCreateRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    amount_cents = int(payload.amount_usd * 100)
    minimum_cents = int(settings.paypal_min_topup_usd) * 100
    if amount_cents < minimum_cents:
        raise HTTPException(422, f"Minimum top-up is ${settings.paypal_min_topup_usd}")
    promo = None
    bonus_cents = 0
    if payload.promo_code:
        promo = promo_for_topup(session, raw_code=payload.promo_code, user_id=principal.actor_id)
        bonus_cents = promo_bonus_cents(promo, amount_cents)
    topup = PayPalTopup(
        id=f"top_{secrets.token_hex(12)}",
        organization_id=principal.organization_id,
        user_id=principal.actor_id,
        amount_cents=amount_cents,
        bonus_cents=bonus_cents,
        promo_code_id=promo.id if promo else None,
        currency="USD",
        status="creating",
    )
    session.add(topup)
    session.commit()
    try:
        order_id, approval_url = PayPalClient(settings).create_order(
            merchant_reference=topup.id,
            amount_cents=amount_cents,
            return_url=f"{settings.web_base_url.rstrip('/')}/billing?paypal=return&topup_id={topup.id}",
            cancel_url=f"{settings.web_base_url.rstrip('/')}/billing?paypal=cancel&topup_id={topup.id}",
        )
    except PayPalError as exc:
        topup.status = "failed"
        topup.failure_code = exc.code
        session.add(topup)
        session.commit()
        raise HTTPException(exc.status_code, {"code": exc.code, "message": "PayPal checkout is unavailable"}) from exc
    topup.paypal_order_id = order_id
    topup.status = "pending_approval"
    session.add(topup)
    session.commit()
    return {
        "topup_id": topup.id,
        "paypal_order_id": order_id,
        "approval_url": approval_url,
        "amount_usd": dollars(amount_cents),
        "bonus_usd": dollars(bonus_cents),
        "total_credit_usd": dollars(amount_cents + bonus_cents),
    }


def _finalize_topup(
    session: Session,
    *,
    topup: PayPalTopup,
    state: PayPalOrderState,
) -> dict[str, object]:
    if topup.status == "captured":
        wallet = ensure_wallet(session, topup.organization_id)
        return {
            "status": "captured",
            "balance_cents": int(wallet.balance_cents),
            "balance_usd": dollars(wallet.balance_cents),
            "credited_usd": dollars(topup.amount_cents + topup.bonus_cents),
        }
    if state.status != "COMPLETED" or not state.capture_id:
        raise HTTPException(409, "PayPal order has not completed")
    if state.currency != topup.currency or state.amount_cents != int(topup.amount_cents):
        topup.status = "amount_mismatch"
        topup.failure_code = "paypal_amount_mismatch"
        session.add(topup)
        session.commit()
        raise HTTPException(409, "PayPal payment amount does not match this top-up")

    bonus_cents = int(topup.bonus_cents)
    promo = None
    promo_failure: str | None = None
    if topup.promo_code_id:
        promo = session.scalar(
            select(PromoCode).where(PromoCode.id == topup.promo_code_id).with_for_update()
        )
        if not promo:
            bonus_cents = 0
        else:
            try:
                ensure_promo_available(session, promo=promo, user_id=topup.user_id)
            except HTTPException as exc:
                # A completed payment must always credit its principal even if a promo became
                # unavailable while the buyer was on PayPal.
                promo_failure = str(exc.detail)
                promo = None
                bonus_cents = 0
            else:
                bonus_cents = promo_bonus_cents(promo, int(topup.amount_cents))

    add_ledger_entry(
        session,
        organization_id=topup.organization_id,
        user_id=topup.user_id,
        amount_cents=int(topup.amount_cents),
        event_type="balance_topup",
        reference_id=topup.id,
        monetary_amount_usd=dollars(topup.amount_cents),
        description="PayPal balance top-up",
        metadata={
            "paypal_order_id": topup.paypal_order_id,
            "paypal_capture_id": state.capture_id,
            "promo_failure": promo_failure,
        },
        commit=False,
    )
    if promo and bonus_cents:
        add_ledger_entry(
            session,
            organization_id=topup.organization_id,
            user_id=topup.user_id,
            amount_cents=bonus_cents,
            event_type="promo_bonus",
            reference_id=topup.id,
            description="Top-up promo bonus",
            metadata={"promo_code_id": promo.id},
            commit=False,
        )
        promo.redemption_count += 1
        session.add_all(
            [
                promo,
                PromoRedemption(
                    id=f"red_{secrets.token_hex(12)}",
                    promo_code_id=promo.id,
                    user_id=topup.user_id,
                    organization_id=topup.organization_id,
                    topup_id=topup.id,
                    bonus_cents=bonus_cents,
                ),
            ]
        )
    topup.bonus_cents = bonus_cents
    topup.paypal_capture_id = state.capture_id
    topup.status = "captured"
    topup.captured_at = datetime.now(UTC)
    session.add(topup)
    session.commit()
    wallet = ensure_wallet(session, topup.organization_id)
    return {
        "status": "captured",
        "balance_cents": int(wallet.balance_cents),
        "balance_usd": dollars(wallet.balance_cents),
        "amount_usd": dollars(topup.amount_cents),
        "bonus_usd": dollars(bonus_cents),
        "credited_usd": dollars(topup.amount_cents + bonus_cents),
    }


@router.post("/topups/paypal/capture")
def capture_paypal_topup(
    payload: TopupCaptureRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    topup = session.scalar(
        select(PayPalTopup)
        .where(
            PayPalTopup.id == payload.topup_id,
            PayPalTopup.organization_id == principal.organization_id,
            PayPalTopup.user_id == principal.actor_id,
        )
        .with_for_update()
    )
    if not topup:
        raise HTTPException(404, "Top-up not found")
    if topup.paypal_order_id != payload.paypal_order_id:
        raise HTTPException(409, "PayPal order does not belong to this top-up")
    if topup.status == "captured":
        return _finalize_topup(
            session,
            topup=topup,
            state=PayPalOrderState(
                payload.paypal_order_id,
                "COMPLETED",
                topup.currency,
                int(topup.amount_cents),
                topup.paypal_capture_id,
                {},
            ),
        )
    try:
        state = PayPalClient(settings).capture_order(payload.paypal_order_id)
    except PayPalError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": "PayPal capture failed"}) from exc
    return _finalize_topup(session, topup=topup, state=state)


@router.post("/topups/paypal/webhook", include_in_schema=False)
async def paypal_webhook(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    payload = await request.json()
    client = PayPalClient(settings)
    try:
        if not client.verify_webhook(payload, {key.lower(): value for key, value in request.headers.items()}):
            raise HTTPException(400, "Invalid PayPal webhook signature")
    except PayPalError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": "PayPal webhook rejected"}) from exc
    if str(payload.get("event_type") or "") != "PAYMENT.CAPTURE.COMPLETED":
        return {"status": "ignored"}
    resource = payload.get("resource") or {}
    order_id = str(resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id") or "")
    if not order_id:
        return {"status": "ignored"}
    topup = session.scalar(
        select(PayPalTopup).where(PayPalTopup.paypal_order_id == order_id).with_for_update()
    )
    if not topup:
        logger.warning("paypal_webhook_unknown_order order_id=%s", order_id)
        return {"status": "ignored"}
    if topup.status != "captured":
        _finalize_topup(session, topup=topup, state=client.get_order(order_id))
    return {"status": "accepted"}
