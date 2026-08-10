from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.config import Settings, get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.email_service import test_token as outbox_token
from apps.api.app.main import app
from apps.api.app.models import Resource, User


@pytest.fixture
def jwt_client(client: TestClient):
    base = get_settings()
    jwt_settings = Settings(
        **{
            **base.model_dump(),
            "app_auth_mode": "jwt",
            "jwt_secret": "test-secret-with-more-than-thirty-two-characters",
            "email_delivery_mode": "log",
            "email_min_resend_seconds": 0,
            "signup_credit_tokens": 1_000,
        }
    )
    app.dependency_overrides[get_settings] = lambda: jwt_settings
    yield client
    app.dependency_overrides.pop(get_settings, None)


def register_and_verify(client: TestClient, label: str) -> dict:
    suffix = uuid4().hex[:10]
    email = f"{label}-{suffix}@example.com"
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": f"{label.title()} Owner",
            "organization_name": f"{label.title()} Organization {suffix}",
            "project_name": f"{label.title()} Project",
            "website_url": f"https://{label}-{suffix}.example.com",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201, response.text
    raw = outbox_token(email, "verify_email")
    assert raw
    verified = client.post("/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200, verified.text
    return {**verified.json(), "email": email, "password": "correct horse battery staple"}


def headers(account: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['access_token']}"}


def test_registration_login_refresh_reset_and_tenant_isolation(jwt_client: TestClient):
    account_a = register_and_verify(jwt_client, "alpha")
    account_b = register_and_verify(jwt_client, "beta")

    projects_a = jwt_client.get("/v1/projects", headers=headers(account_a))
    projects_b = jwt_client.get("/v1/projects", headers=headers(account_b))
    assert projects_a.status_code == projects_b.status_code == 200
    project_a = projects_a.json()["items"][0]
    project_b = projects_b.json()["items"][0]
    assert project_a["organization_id"] != project_b["organization_id"]
    assert project_a["id"] != project_b["id"]
    brand_a = jwt_client.get(f"/v1/projects/{project_a['id']}/brand-profile", headers=headers(account_a))
    assert brand_a.status_code == 200
    assert brand_a.json()["identity"]["name"] == "Alpha Project"
    assert "SubSchool" not in brand_a.text
    analytics_a = jwt_client.get(f"/v1/projects/{project_a['id']}/analytics/summary", headers=headers(account_a))
    assert analytics_a.status_code == 200
    assert analytics_a.json()["patterns"] == []
    strategy_a = jwt_client.get(f"/v1/projects/{project_a['id']}/strategy", headers=headers(account_a))
    assert strategy_a.status_code == 200
    assert strategy_a.json()["cold_start"] is True
    assert strategy_a.json()["sample_size"] == 0
    assert strategy_a.json()["confidence"] == 0
    calendar_a = jwt_client.get(f"/v1/projects/{project_a['id']}/calendar", headers=headers(account_a))
    assert calendar_a.status_code == 200
    assert calendar_a.json()["timezone"] == "UTC"
    assert calendar_a.json()["cadence"] == {"daily_cap": 0, "weekly_cap": 0, "minimum_gap_hours": 0.0}

    cross_tenant = jwt_client.get(f"/v1/projects/{project_a['id']}", headers=headers(account_b))
    assert cross_tenant.status_code == 404
    assert jwt_client.get("/v1/projects").status_code == 401

    login = jwt_client.post(
        "/v1/auth/login", json={"email": account_a["email"], "password": account_a["password"]}
    )
    assert login.status_code == 200
    first_refresh = login.json()["refresh_token"]
    rotated = jwt_client.post("/v1/auth/refresh", json={"token": first_refresh})
    assert rotated.status_code == 200
    replay = jwt_client.post("/v1/auth/refresh", json={"token": first_refresh})
    assert replay.status_code == 401
    assert jwt_client.post("/v1/auth/refresh", json={"token": rotated.json()["refresh_token"]}).status_code == 401

    reset_request = jwt_client.post("/v1/auth/password-reset/request", json={"email": account_a["email"]})
    assert reset_request.status_code == 200
    reset = outbox_token(account_a["email"], "password_reset")
    assert reset
    confirmed = jwt_client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": reset, "password": "a completely new password"},
    )
    assert confirmed.status_code == 200
    assert jwt_client.post(
        "/v1/auth/login", json={"email": account_a["email"], "password": account_a["password"]}
    ).status_code == 401
    assert jwt_client.post(
        "/v1/auth/login", json={"email": account_a["email"], "password": "a completely new password"}
    ).status_code == 200


def test_billing_promo_admin_and_usage_charge(jwt_client: TestClient):
    admin = register_and_verify(jwt_client, "platform-admin")
    customer = register_and_verify(jwt_client, "customer")
    assert jwt_client.get("/v1/platform-admin/overview", headers=headers(customer)).status_code == 403

    with SessionLocal() as session:
        admin_user = session.scalar(select(User).where(User.email == admin["email"]))
        assert admin_user
        admin_user.is_platform_admin = True
        session.add(admin_user)
        customer_project = session.scalar(
            select(Resource).where(
                Resource.kind == "project", Resource.organization_id == customer["organization_id"]
            )
        )
        assert customer_project
        customer_project.status = "active"
        session.add(customer_project)
        session.commit()

    overview = jwt_client.get("/v1/platform-admin/overview", headers=headers(admin))
    assert overview.status_code == 200
    promo = jwt_client.post(
        "/v1/platform-admin/promo-codes",
        headers=headers(admin),
        json={
            "code": f"TEST-{uuid4().hex[:8]}",
            "kind": "bundle",
            "credit_tokens": 750,
            "subscription_days": 30,
            "max_redemptions": 1,
        },
    )
    assert promo.status_code == 201, promo.text
    redeemed = jwt_client.post(
        "/v1/billing/promo-codes/redeem",
        headers=headers(customer),
        json={"code": promo.json()["code"]},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["balance_tokens"] == 1_720
    assert jwt_client.post(
        "/v1/billing/promo-codes/redeem",
        headers=headers(customer),
        json={"code": promo.json()["code"]},
    ).status_code in {409, 410}

    generation = jwt_client.post(
        f"/v1/projects/{customer['default_project_id']}/generation-jobs",
        headers=headers(customer),
        json={"title": "A customer-owned production", "aspect_ratios": ["9:16"], "variants": 1},
    )
    assert generation.status_code == 202, generation.text
    summary = jwt_client.get("/v1/billing/summary", headers=headers(customer))
    assert summary.status_code == 200
    assert summary.json()["balance_tokens"] == 1_220
    ledger = jwt_client.get("/v1/billing/ledger", headers=headers(customer)).json()["items"]
    assert any(item["feature_key"] == "video.generate" and item["amount_tokens"] == -500 for item in ledger)
