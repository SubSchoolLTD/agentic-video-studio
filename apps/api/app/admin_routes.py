from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .billing import add_ledger_entry, ensure_wallet, hash_promo
from .database import get_db
from .models import CreditLedger, PriceRule, PromoCode, Resource, User, Wallet
from .security import Principal, get_principal

router = APIRouter(prefix="/v1/platform-admin", tags=["platform-admin"])


def platform_admin(principal: Principal = Depends(get_principal)) -> Principal:
    principal.require_platform_admin()
    return principal


class UserPatch(BaseModel):
    status: str | None = Field(default=None, pattern=r"^(active|blocked|pending_verification)$")
    is_platform_admin: bool | None = None


class CreditAdjustment(BaseModel):
    amount_tokens: int = Field(ge=-10_000_000, le=10_000_000)
    description: str = Field(min_length=3, max_length=300)
    deposited_usd: float | None = Field(default=None, ge=0, le=1_000_000)


class PromoCreate(BaseModel):
    code: str | None = Field(default=None, min_length=3, max_length=64)
    kind: str = Field(pattern=r"^(ai_tokens|subscription|bundle)$")
    credit_tokens: int = Field(default=0, ge=0, le=100_000_000)
    subscription_days: int = Field(default=0, ge=0, le=3650)
    max_redemptions: int | None = Field(default=None, ge=1, le=10_000_000)
    expires_at: datetime | None = None


class PromoPatch(BaseModel):
    is_active: bool | None = None
    max_redemptions: int | None = Field(default=None, ge=1, le=10_000_000)
    expires_at: datetime | None = None


class PricePatch(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=160)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    provider_cost_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    charge_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    margin_percent: float | None = Field(default=None, ge=-100, le=100_000)
    is_active: bool | None = None


def _membership_for_user(session: Session, user_id: str) -> Resource | None:
    return session.scalar(
        select(Resource)
        .where(Resource.kind == "membership", Resource.data["actor_id"].as_string() == user_id)
        .order_by(Resource.created_at.asc())
    )


def _serialize_user(session: Session, user: User) -> dict[str, object]:
    membership = _membership_for_user(session, user.id)
    organization = session.get(Resource, membership.organization_id) if membership else None
    wallet = session.get(Wallet, membership.organization_id) if membership else None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "email_verified": user.email_verified_at is not None,
        "is_platform_admin": bool(user.is_platform_admin),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat(),
        "organization_id": membership.organization_id if membership else None,
        "organization_name": organization.data.get("name") if organization else None,
        "role": membership.data.get("role") if membership else None,
        "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
    }


@router.get("/overview")
def overview(
    _: Principal = Depends(platform_admin), session: Session = Depends(get_db)
) -> dict[str, object]:
    total_users = int(session.scalar(select(func.count()).select_from(User)) or 0)
    active_users = int(session.scalar(select(func.count()).select_from(User).where(User.status == "active")) or 0)
    organizations = int(
        session.scalar(select(func.count()).select_from(Resource).where(Resource.kind == "organization")) or 0
    )
    credited = int(
        session.scalar(select(func.coalesce(func.sum(CreditLedger.amount_tokens), 0)).where(CreditLedger.amount_tokens > 0)) or 0
    )
    spent = abs(
        int(session.scalar(select(func.coalesce(func.sum(CreditLedger.amount_tokens), 0)).where(CreditLedger.amount_tokens < 0)) or 0)
    )
    deposits = float(
        session.scalar(select(func.coalesce(func.sum(CreditLedger.monetary_amount_usd), 0)).where(CreditLedger.monetary_amount_usd > 0)) or 0
    )
    return {
        "users": {"total": total_users, "active": active_users, "pending": total_users - active_users},
        "organizations": organizations,
        "tokens": {"credited": credited, "spent": spent, "outstanding": credited - spent},
        "money": {"deposited_usd": round(deposits, 2)},
    }


@router.get("/users")
def users(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = None,
    limit: int = 100,
    _: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    statement = select(User)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
    if status:
        statement = statement.where(User.status == status)
    items = list(session.scalars(statement.order_by(User.created_at.desc()).limit(min(max(limit, 1), 500))))
    return {"items": [_serialize_user(session, item) for item in items], "count": len(items)}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: UserPatch,
    principal: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    changes = payload.model_dump(exclude_none=True)
    if user.id == principal.actor_id and changes.get("status") == "blocked":
        raise HTTPException(409, "You cannot block your own administrator account")
    if user.id == principal.actor_id and changes.get("is_platform_admin") is False:
        raise HTTPException(409, "You cannot remove your own administrator access")
    for key, value in changes.items():
        setattr(user, key, value)
    if "status" in changes or "is_platform_admin" in changes:
        user.token_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    return _serialize_user(session, user)


@router.post("/users/{user_id}/credits")
def adjust_credits(
    user_id: str,
    payload: CreditAdjustment,
    principal: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    user = session.get(User, user_id)
    membership = _membership_for_user(session, user_id) if user else None
    if not user or not membership:
        raise HTTPException(404, "User or workspace not found")
    entry = add_ledger_entry(
        session,
        organization_id=membership.organization_id,
        user_id=user.id,
        amount_tokens=payload.amount_tokens,
        event_type="admin_topup" if payload.amount_tokens >= 0 else "admin_debit",
        reference_id=principal.actor_id,
        description=payload.description,
        monetary_amount_usd=payload.deposited_usd,
        allow_negative_balance=False,
    )
    wallet = ensure_wallet(session, membership.organization_id)
    return {"ledger_id": entry.id, "balance_tokens": int(wallet.balance_tokens)}


@router.get("/promo-codes")
def promo_codes(
    _: Principal = Depends(platform_admin), session: Session = Depends(get_db)
) -> dict[str, object]:
    items = list(session.scalars(select(PromoCode).order_by(PromoCode.created_at.desc())))
    return {
        "items": [
            {
                "id": item.id,
                "code": item.code_prefix,
                "kind": item.kind,
                "credit_tokens": int(item.credit_tokens),
                "subscription_days": item.subscription_days,
                "max_redemptions": item.max_redemptions,
                "redemption_count": item.redemption_count,
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "is_active": item.is_active,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]
    }


@router.post("/promo-codes", status_code=201)
def create_promo(
    payload: PromoCreate,
    principal: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    raw = (payload.code or f"FRAME-{secrets.token_urlsafe(8)}").strip().upper()
    if session.scalar(select(PromoCode).where(PromoCode.code_hash == hash_promo(raw))):
        raise HTTPException(409, "Promo code already exists")
    promo = PromoCode(
        id=f"pro_{secrets.token_hex(12)}",
        code_hash=hash_promo(raw),
        code_prefix=raw if len(raw) <= 16 else f"{raw[:12]}…",
        kind=payload.kind,
        credit_tokens=payload.credit_tokens,
        subscription_days=payload.subscription_days,
        max_redemptions=payload.max_redemptions,
        expires_at=payload.expires_at,
        created_by_user_id=principal.actor_id,
    )
    session.add(promo)
    session.commit()
    return {"id": promo.id, "code": raw, "message": "Copy this code now; only its hash is stored."}


@router.patch("/promo-codes/{promo_id}")
def patch_promo(
    promo_id: str,
    payload: PromoPatch,
    _: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    promo = session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(404, "Promo code not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(promo, key, value)
    session.add(promo)
    session.commit()
    return {"id": promo.id, "is_active": promo.is_active, "max_redemptions": promo.max_redemptions}


@router.get("/pricing")
def pricing(
    _: Principal = Depends(platform_admin), session: Session = Depends(get_db)
) -> dict[str, object]:
    rules = list(session.scalars(select(PriceRule).order_by(PriceRule.label)))
    return {
        "items": [
            {
                "feature_key": item.feature_key,
                "label": item.label,
                "unit": item.unit,
                "provider_cost_usd": float(item.provider_cost_usd),
                "charge_tokens": int(item.charge_tokens),
                "margin_percent": float(item.margin_percent),
                "is_active": item.is_active,
            }
            for item in rules
        ]
    }


@router.patch("/pricing/{feature_key}")
def patch_price(
    feature_key: str,
    payload: PricePatch,
    _: Principal = Depends(platform_admin),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    rule = session.get(PriceRule, feature_key)
    if not rule:
        raise HTTPException(404, "Price rule not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(rule, key, value)
    session.add(rule)
    session.commit()
    return {
        "feature_key": rule.feature_key,
        "charge_tokens": int(rule.charge_tokens),
        "provider_cost_usd": float(rule.provider_cost_usd),
        "margin_percent": float(rule.margin_percent),
        "is_active": rule.is_active,
    }
