from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .billing import ensure_wallet, redeem_promo
from .config import Settings, get_settings
from .database import get_db
from .models import CreditLedger, PriceRule, Subscription
from .security import Principal, get_principal

router = APIRouter(prefix="/v1/billing", tags=["billing"])


class PromoRedeemRequest(BaseModel):
    code: str = Field(min_length=3, max_length=64)


@router.get("/public-pricing")
def public_pricing(
    session: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, object]:
    """Return the current customer-facing token rates without exposing provider costs or margins."""
    prices = list(
        session.scalars(select(PriceRule).where(PriceRule.is_active.is_(True)).order_by(PriceRule.label))
    )
    return {
        "beta_monthly_usd": 0,
        "welcome_tokens": settings.signup_credit_tokens,
        "prices": [
            {
                "feature_key": item.feature_key,
                "label": item.label,
                "unit": item.unit,
                "charge_tokens": int(item.charge_tokens),
            }
            for item in prices
        ],
    }


@router.get("/summary")
def billing_summary(
    principal: Principal = Depends(get_principal), session: Session = Depends(get_db)
) -> dict[str, object]:
    wallet = ensure_wallet(session, principal.organization_id)
    subscription = session.get(Subscription, principal.organization_id)
    prices = list(session.scalars(select(PriceRule).where(PriceRule.is_active.is_(True)).order_by(PriceRule.label)))
    return {
        "balance_tokens": int(wallet.balance_tokens),
        "subscription": {
            "plan": subscription.plan if subscription else "free",
            "status": subscription.status if subscription else "active",
            "expires_at": subscription.expires_at.isoformat() if subscription and subscription.expires_at else None,
        },
        "prices": [
            {
                "feature_key": item.feature_key,
                "label": item.label,
                "unit": item.unit,
                "charge_tokens": int(item.charge_tokens),
            }
            for item in prices
        ],
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
        "items": [
            {
                "id": item.id,
                "amount_tokens": int(item.amount_tokens),
                "event_type": item.event_type,
                "feature_key": item.feature_key,
                "reference_id": item.reference_id,
                "description": item.description,
                "monetary_amount_usd": float(item.monetary_amount_usd) if item.monetary_amount_usd is not None else None,
                "created_at": item.created_at.isoformat(),
            }
            for item in entries
        ]
    }


@router.post("/promo-codes/redeem")
def redeem(
    payload: PromoRedeemRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    return redeem_promo(
        session,
        raw_code=payload.code,
        user_id=principal.actor_id,
        organization_id=principal.organization_id,
    )
