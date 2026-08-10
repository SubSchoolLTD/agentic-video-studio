from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import Base, Resource, User
from apps.api.app.seed import seed_application, seed_demo


def test_production_bootstrap_replaces_demo_fixtures_with_real_admin_and_cold_start() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="production",
        app_auth_mode="jwt",
        jwt_secret="production-test-secret-longer-than-thirty-two-characters",
        provider_mode="live",
        parallel_api_key="parallel-test",
        google_cloud_project="production-test",
        google_cloud_storage_bucket="production-test-media",
        email_delivery_mode="sendpulse",
        sendpulse_id="sendpulse-test",
        sendpulse_secret="sendpulse-secret-test",
        bootstrap_admin_email="maksim@subschool.us",
    )

    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        seed_demo(session)
        seed_application(session, settings)

        admin = session.scalar(select(User).where(User.email == "maksim@subschool.us"))
        assert admin and admin.status == "active" and admin.is_platform_admin
        membership = session.scalar(
            select(Resource).where(Resource.kind == "membership", Resource.organization_id == "org_demo")
        )
        assert membership and membership.data["actor_id"] == admin.id
        active_strategy = session.scalar(
            select(Resource).where(
                Resource.kind == "strategy",
                Resource.organization_id == "org_demo",
                Resource.status == "active",
            )
        )
        assert active_strategy and active_strategy.data["cold_start"] is True
        assert active_strategy.data["sample_size"] == 0
        fixtures = list(session.scalars(select(Resource).where(Resource.organization_id == "org_demo")))
        assert not any(item.data.get("demo_data") or item.data.get("mode") == "mock" for item in fixtures)
