from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .billing import (
    add_ledger_entry,
    dollars,
    ensure_wallet,
    promo_for_redemption,
)
from .config import Settings, get_settings
from .database import get_db
from .models import CreditLedger, PayPalTopup, PriceRule, PromoRedemption
from .paypal import PayPalClient, PayPalError, PayPalOrderState
from .security import Principal, get_principal

router = APIRouter(prefix="/v1/billing", tags=["billing"])
logger = logging.getLogger("avs.billing")


class TopupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_usd: Decimal = Field(ge=Decimal("12.00"), le=Decimal("100000.00"))
    return_path: str = Field(default="/billing", min_length=1, max_length=500)

    @field_validator("amount_usd")
    @classmethod
    def two_decimal_places(cls, value: Decimal) -> Decimal:
        normalized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if value != normalized:
            raise ValueError("amount_usd supports at most two decimal places")
        return normalized

    @field_validator("return_path")
    @classmethod
    def safe_return_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "\n" in value or "\r" in value:
            raise ValueError("return_path must be a local application path")
        return value


class TopupCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topup_id: str = Field(min_length=8, max_length=64)
    paypal_order_id: str = Field(min_length=8, max_length=64)


class PromoRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=3, max_length=64)


def _price(rule: PriceRule) -> dict[str, object]:
    return {
        "feature_key": rule.feature_key,
        "label": rule.label,
        "unit": rule.unit,
        "charge_cents": int(rule.charge_cents),
        "charge_usd": dollars(rule.charge_cents),
    }


def _return_url(base_url: str, path: str, *, paypal: str, topup_id: str) -> str:
    target = urlsplit(f"{base_url.rstrip('/')}{path}")
    query = dict(parse_qsl(target.query, keep_blank_values=True))
    query.update({"paypal": paypal, "topup_id": topup_id})
    return urlunsplit((target.scheme, target.netloc, target.path, urlencode(query), ""))


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
    topup = PayPalTopup(
        id=f"top_{secrets.token_hex(12)}",
        organization_id=principal.organization_id,
        user_id=principal.actor_id,
        amount_cents=amount_cents,
        bonus_cents=0,
        promo_code_id=None,
        currency="USD",
        status="creating",
    )
    session.add(topup)
    session.commit()
    try:
        order_id, approval_url = PayPalClient(settings).create_order(
            merchant_reference=topup.id,
            amount_cents=amount_cents,
            return_url=_return_url(
                settings.web_base_url,
                payload.return_path,
                paypal="return",
                topup_id=topup.id,
            ),
            cancel_url=_return_url(
                settings.web_base_url,
                payload.return_path,
                paypal="cancel",
                topup_id=topup.id,
            ),
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
        "total_credit_usd": dollars(amount_cents),
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
            "credited_usd": dollars(topup.amount_cents),
        }
    if state.status != "COMPLETED" or not state.capture_id:
        raise HTTPException(409, "PayPal order has not completed")
    if state.currency != topup.currency or state.amount_cents != int(topup.amount_cents):
        topup.status = "amount_mismatch"
        topup.failure_code = "paypal_amount_mismatch"
        session.add(topup)
        session.commit()
        raise HTTPException(409, "PayPal payment amount does not match this top-up")

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
        },
        commit=False,
    )
    topup.bonus_cents = 0
    topup.promo_code_id = None
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
        "credited_usd": dollars(topup.amount_cents),
    }


@router.post("/promo-codes/redeem")
def redeem_promo_code(
    payload: PromoRedeemRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    promo = promo_for_redemption(
        session,
        raw_code=payload.code,
        user_id=principal.actor_id,
        lock=True,
    )
    amount_cents = int(promo.bonus_cents)
    if amount_cents <= 0:
        raise HTTPException(409, "Promo code has no balance credit")
    redemption = PromoRedemption(
        id=f"red_{secrets.token_hex(12)}",
        promo_code_id=promo.id,
        user_id=principal.actor_id,
        organization_id=principal.organization_id,
        topup_id=None,
        bonus_cents=amount_cents,
    )
    session.add(redemption)
    session.flush()
    promo.redemption_count += 1
    session.add(promo)
    add_ledger_entry(
        session,
        organization_id=principal.organization_id,
        user_id=principal.actor_id,
        amount_cents=amount_cents,
        event_type="promo_credit",
        reference_id=redemption.id,
        description="Promo code balance credit",
        metadata={"promo_code_id": promo.id},
        commit=False,
    )
    session.commit()
    wallet = ensure_wallet(session, principal.organization_id)
    return {
        "status": "redeemed",
        "credited_usd": dollars(amount_cents),
        "balance_usd": dollars(wallet.balance_cents),
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
