from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.config import Settings, get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.email_service import test_token as outbox_token
from apps.api.app.main import app
from apps.api.app.models import AuthIdentity, PayPalTopup, Resource, User, Wallet
from apps.api.app.paypal import PayPalClient, PayPalOrderState
from apps.api.app.routes import _maybe_send_low_balance_email
from apps.api.app.social_browser import BrowserLoginResult, SocialBrowserError


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
            "paypal_client_id": "test-paypal-client",
            "paypal_secret": "test-paypal-secret",
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
    assert response.json()["email_sent"] is True
    raw = outbox_token(email, "verify_email")
    assert raw
    verified = client.post("/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200, verified.text
    return {**verified.json(), "email": email, "password": "correct horse battery staple"}


def headers(account: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['access_token']}"}


@pytest.mark.parametrize("provider", ["tiktok", "instagram"])
@pytest.mark.parametrize("verify", [False, True])
def test_provider_rejected_credentials_do_not_revoke_studio_session(jwt_client, monkeypatch, provider, verify):
    account = register_and_verify(jwt_client, "social-session")
    configured = app.dependency_overrides[get_settings]().model_copy(update={"provider_mode": "live"})
    app.dependency_overrides[get_settings] = lambda: configured
    endpoint = f"/v1/projects/{account['default_project_id']}/connections/{provider}/browser-login"
    payload = {"username": "demo@example.test", "password": "transient-social-password"}
    code = "invalid_verification_code" if verify else "invalid_credentials"

    def rejected(*_args, **_kwargs):
        raise SocialBrowserError("Provider rejected sign-in", code=code)

    if verify:
        monkeypatch.setattr("apps.api.app.routes.connect_social_account", lambda *_args, **_kwargs: BrowserLoginResult(
            status="verification_required", display_name="demo", external_account_id="demo",
            storage_state={"cookies": [], "origins": []}, page_url=f"https://www.{provider}.com/challenge",
            challenge_kind="one_time_code",
        ))
        pending = jwt_client.post(endpoint, headers=headers(account), json=payload)
        assert pending.status_code == 200
        endpoint = f"/v1/connections/{pending.json()['id']}/browser-verify"
        payload = {"code": "000000"}
        monkeypatch.setattr("apps.api.app.routes.verify_social_account", rejected)
    else:
        monkeypatch.setattr("apps.api.app.routes.connect_social_account", rejected)

    response = jwt_client.post(endpoint, headers=headers(account), json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"]["auth_scope"] == "provider"
    assert response.json()["error"]["details"]["provider"] == provider
    assert "transient-social-password" not in response.text
    assert jwt_client.get("/v1/me", headers=headers(account)).status_code == 200
    assert jwt_client.post("/v1/auth/refresh", json={"token": account["refresh_token"]}).status_code == 200
    assert jwt_client.post(endpoint, json=payload).status_code == 401


def test_minimal_registration_and_google_identity_share_one_account(jwt_client: TestClient, monkeypatch):
    email = f"linked-{uuid4().hex[:10]}@example.com"
    registered = jwt_client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Linked Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    base = get_settings()
    configured = Settings(**{**base.model_dump(), "google_oauth_client_id": "test-google-client.apps.googleusercontent.com"})
    jwt_client.app.dependency_overrides[get_settings] = lambda: configured
    monkeypatch.setattr(
        "apps.api.app.auth_routes.google_id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "sub": "google-subject-linked-account",
            "email": email,
            "email_verified": True,
            "name": "Linked Owner",
        },
    )
    google = jwt_client.post("/v1/auth/google", json={"credential": "x" * 120})
    assert google.status_code == 200, google.text
    assert google.json()["user"]["onboarding_complete"] is False
    assert google.json()["user"]["email"] == email
    with SessionLocal() as session:
        assert session.scalar(select(User).where(User.email == email))
        assert len(list(session.scalars(select(User).where(User.email == email)))) == 1
        identity = session.scalar(select(AuthIdentity).where(AuthIdentity.provider_subject == "google-subject-linked-account"))
        assert identity
    login = jwt_client.post(
        "/v1/auth/login", json={"email": email, "password": "correct horse battery staple"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == google.json()["user"]["id"]


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


def test_billing_paypal_promo_admin_and_usage_charge(jwt_client: TestClient, monkeypatch):
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

    forbidden_test_mode = jwt_client.post(
        f"/v1/projects/{customer['default_project_id']}/generation-jobs",
        headers=headers(customer),
        json={
            "title": "A customer must not bypass billing",
            "aspect_ratios": ["9:16"],
            "test_mode": True,
        },
    )
    assert forbidden_test_mode.status_code == 403

    overview = jwt_client.get("/v1/platform-admin/overview", headers=headers(admin))
    assert overview.status_code == 200
    assert overview.json()["retention"]["day_7"]["definition"] == "Any authenticated activity on or after day 7"
    promo = jwt_client.post(
        "/v1/platform-admin/promo-codes",
        headers=headers(admin),
        json={
            "code": f"TEST-{uuid4().hex[:8]}",
            "amount_cents": 220,
            "max_redemptions": 1,
        },
    )
    assert promo.status_code == 201, promo.text
    promo_code = promo.json()["code"]
    redeemed = jwt_client.post(
        "/v1/billing/promo-codes/redeem",
        headers=headers(customer),
        json={"code": promo_code},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["credited_usd"] == 2.2
    assert redeemed.json()["balance_usd"] == 2.2
    repeated_redemption = jwt_client.post(
        "/v1/billing/promo-codes/redeem",
        headers=headers(customer),
        json={"code": promo_code},
    )
    assert repeated_redemption.status_code == 409

    order_id = f"PAYPAL-{uuid4().hex[:12]}"
    paypal_order_args: dict[str, object] = {}
    def create_paypal_order(_client, **kwargs):
        paypal_order_args.update(kwargs)
        return order_id, f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"

    monkeypatch.setattr(
        PayPalClient,
        "create_order",
        create_paypal_order,
    )
    monkeypatch.setattr(
        PayPalClient,
        "capture_order",
        lambda self, value: PayPalOrderState(value, "COMPLETED", "USD", 1_200, "CAPTURE-TEST", {}),
    )
    too_small = jwt_client.post(
        "/v1/billing/topups/paypal",
        headers=headers(customer),
        json={"amount_usd": "11.99"},
    )
    assert too_small.status_code == 422
    unsafe_return = jwt_client.post(
        "/v1/billing/topups/paypal",
        headers=headers(customer),
        json={"amount_usd": "12.00", "return_path": "//malicious.example/steal"},
    )
    assert unsafe_return.status_code == 422
    created_topup = jwt_client.post(
        "/v1/billing/topups/paypal",
        headers=headers(customer),
        json={"amount_usd": "12.00", "return_path": "/funding?plan=month&activate=1"},
    )
    assert created_topup.status_code == 201, created_topup.text
    assert created_topup.json()["amount_usd"] == 12
    assert "/funding?plan=month&activate=1&paypal=return&topup_id=" in str(paypal_order_args["return_url"])
    assert "/funding?plan=month&activate=1&paypal=cancel&topup_id=" in str(paypal_order_args["cancel_url"])
    captured = jwt_client.post(
        "/v1/billing/topups/paypal/capture",
        headers=headers(customer),
        json={
            "topup_id": created_topup.json()["topup_id"],
            "paypal_order_id": order_id,
        },
    )
    assert captured.status_code == 200, captured.text
    assert captured.json()["balance_cents"] == 1_420
    assert captured.json()["credited_usd"] == 12
    repeated_capture = jwt_client.post(
        "/v1/billing/topups/paypal/capture",
        headers=headers(customer),
        json={
            "topup_id": created_topup.json()["topup_id"],
            "paypal_order_id": order_id,
        },
    )
    assert repeated_capture.status_code == 200
    assert repeated_capture.json()["balance_cents"] == 1_420

    monkeypatch.setattr(jwt_client.app.state.workflow, "schedule", lambda _job_id: None)
    generation = jwt_client.post(
        f"/v1/projects/{customer['default_project_id']}/generation-jobs",
        headers=headers(customer),
        json={
            "title": "A customer-owned production",
            "aspect_ratios": ["9:16"],
            "variants": 1,
            "max_cost_usd": 30,
        },
    )
    assert generation.status_code == 202, generation.text
    summary = jwt_client.get("/v1/billing/summary", headers=headers(customer))
    assert summary.status_code == 200
    assert summary.json()["balance_cents"] == 604
    ledger = jwt_client.get("/v1/billing/ledger", headers=headers(customer)).json()["items"]
    assert any(item["feature_key"] == "video.generate" and item["amount_cents"] == -816 for item in ledger)

    insufficient = jwt_client.post(
        f"/v1/projects/{customer['default_project_id']}/generation-jobs",
        headers=headers(customer),
        json={"title": "One production too many", "aspect_ratios": ["9:16"], "max_cost_usd": 30},
    )
    assert insufficient.status_code == 402
    assert insufficient.json()["error"] == {
        "code": "insufficient_balance",
        "message": "Not enough balance for this action",
        "details": {
            "required_cents": 816,
            "available_cents": 604,
            "shortfall_cents": 212,
            "currency": "USD",
        },
        "request_id": insufficient.headers["X-Request-ID"],
        "retryable": False,
    }

    with SessionLocal() as session:
        customer_user = session.scalar(select(User).where(User.email == customer["email"]))
        assert customer_user
    topup = jwt_client.post(
        f"/v1/platform-admin/users/{customer_user.id}/credits",
        headers=headers(admin),
        json={"amount_cents": 2_000, "deposited_usd": 20, "description": "Recorded customer payment"},
    )
    assert topup.status_code == 200

    # Voice generation is independent from visual style and native Veo audio keeps its own price rule.
    native_generation = jwt_client.post(
        f"/v1/projects/{customer['default_project_id']}/generation-jobs",
        headers=headers(customer),
        json={
            "title": "Native storytelling sketch",
            "visual_mode": "storytelling",
            "audio_mode": "veo_native",
            "aspect_ratios": ["9:16"],
            "variants": 1,
            "max_cost_usd": 30,
        },
    )
    assert native_generation.status_code == 202, native_generation.text
    native_job = jwt_client.get(
        f"/v1/generation-jobs/{native_generation.json()['generation_job_id']}", headers=headers(customer)
    ).json()
    assert native_job["title"] == "Native storytelling sketch"
    assert native_job["visual_mode"] == "storytelling"
    assert native_job["audio_mode"] == "veo_native"
    assert native_job["continue_scenes"] is False
    assert native_job["character_id"] is None
    assert native_job["estimated_cost"]["basis"] == "video.generate_native_audio"

    # Provider spend is a cost, never a customer deposit. Only explicit paid/admin top-ups count as cash.
    with SessionLocal() as session:
        customer_user = session.scalar(select(User).where(User.email == customer["email"]))
        assert customer_user
        customer_user.created_at = datetime.now(UTC) - timedelta(days=31)
        session.add(customer_user)
        session.commit()
    overview = jwt_client.get("/v1/platform-admin/overview", headers=headers(admin)).json()
    assert overview["money"]["deposited_usd"] >= 32
    assert overview["money"]["provider_cost_usd"] > 0
    assert overview["retention"]["day_30"]["retained"] >= 1
    assert any(item["feature_key"] == "video.generate_native_audio" for item in overview["usage_by_feature"])

    prices = jwt_client.get("/v1/platform-admin/pricing", headers=headers(admin)).json()["items"]
    native_price = next(item for item in prices if item["feature_key"] == "video.generate_native_audio")
    assert native_price["provider"] == "Google + Parallel"
    assert "veo-3.1" in native_price["model_id"]


def test_public_pricing_exposes_customer_rates_without_internal_economics(jwt_client: TestClient):
    response = jwt_client.get("/v1/billing/public-pricing")
    assert response.status_code == 200
    payload = response.json()
    assert payload["currency"] == "USD"
    assert payload["minimum_topup_usd"] == 12
    assert {item["feature_key"] for item in payload["prices"]} == {
        "project.website_analysis",
        "research.run",
        "video.generate",
        "video.generate_native_audio",
        "video.scene_regenerate",
        "video.scene_regenerate_native_audio",
        "character.generate",
    }
    assert all("provider_cost_usd" not in item and "margin_percent" not in item for item in payload["prices"])
    assert all("charge_cents" in item and "charge_usd" in item for item in payload["prices"])


def test_onboarding_finishes_on_funding_and_payment_activation_starts_research(
    jwt_client: TestClient,
    monkeypatch,
):
    account = register_and_verify(jwt_client, "funding-onboarding")
    project_id = account["default_project_id"]
    saved = jwt_client.patch(
        f"/v1/projects/{project_id}/onboarding/preferences",
        headers=headers(account),
        json={
            "selling_percent": 20,
            "viral_percent": 30,
            "informative_percent": 50,
            "videos_per_week": 3,
            "average_duration_seconds": 30,
            "audio_quality": "premium",
            "automation_mode": "videos",
        },
    )
    assert saved.status_code == 200, saved.text
    completed = jwt_client.post(f"/v1/projects/{project_id}/onboarding/complete", headers=headers(account))
    assert completed.status_code == 200, completed.text
    assert completed.json()["next_url"] == "/funding?source=onboarding"

    funding = jwt_client.get(f"/v1/projects/{project_id}/funding-status", headers=headers(account))
    assert funding.status_code == 200, funding.text
    plan = funding.json()
    assert plan["needs_topup"] is True
    assert [item["id"] for item in plan["options"]] == ["week", "month", "quarter"]
    assert [item["video_count"] for item in plan["options"]] == [3, 12, 36]
    assert all(item["amount_usd"] == int(item["amount_usd"]) for item in plan["options"])

    unfunded = jwt_client.post(f"/v1/projects/{project_id}/automation/activate", headers=headers(account))
    assert unfunded.status_code == 402

    with SessionLocal() as session:
        wallet = session.get(Wallet, account["organization_id"])
        assert wallet
        wallet.balance_cents = 12_000
        session.add(wallet)
        session.commit()

    async def no_research_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr("apps.api.app.routes._run_research_task", no_research_task)
    activated = jwt_client.post(f"/v1/projects/{project_id}/automation/activate", headers=headers(account))
    assert activated.status_code == 202, activated.text
    assert activated.json()["status"] == "activated"
    assert activated.json()["research_run_id"]
    repeated = jwt_client.post(f"/v1/projects/{project_id}/automation/activate", headers=headers(account))
    assert repeated.status_code == 202
    assert repeated.json()["research_run_id"] == activated.json()["research_run_id"]

    with SessionLocal() as session:
        project = session.get(Resource, project_id)
        assert project and project.status == "active"
        runs = list(
            session.scalars(
                select(Resource).where(
                    Resource.kind == "research_run",
                    Resource.project_id == project_id,
                    Resource.data["trigger_type"].as_string() == "funding_activation",
                )
            )
        )
        assert len(runs) == 1


def test_low_balance_email_is_sent_once_per_captured_topup(jwt_client: TestClient, monkeypatch):
    account = register_and_verify(jwt_client, "low-balance-email")
    project_id = account["default_project_id"]
    with SessionLocal() as session:
        project = session.get(Resource, project_id)
        assert project
        project.data = {
            **project.data,
            "automation_mode": "videos",
            "settings": {
                **dict(project.data.get("settings") or {}),
                "production": {"videos_per_week": 2, "average_duration_seconds": 30, "audio_quality": "premium"},
            },
        }
        topup = PayPalTopup(
            id=f"top_{uuid4().hex[:24]}",
            organization_id=account["organization_id"],
            user_id=account["user"]["id"],
            paypal_order_id=f"ORDER-{uuid4().hex[:16]}",
            paypal_capture_id=f"CAPTURE-{uuid4().hex[:16]}",
            amount_cents=1_200,
            bonus_cents=0,
            currency="USD",
            status="captured",
            captured_at=datetime.now(UTC),
        )
        session.add_all([project, topup])
        session.commit()

    deliveries: list[str] = []
    def deliver(**kwargs):
        deliveries.append(kwargs["user"].email)
        return True

    monkeypatch.setattr("apps.api.app.routes.send_low_balance_email", deliver)
    with SessionLocal() as session:
        project = session.get(Resource, project_id)
        assert project
        assert _maybe_send_low_balance_email(session, project=project, settings=get_settings()) is True
        assert _maybe_send_low_balance_email(session, project=project, settings=get_settings()) is False
    assert deliveries == [account["email"]]
