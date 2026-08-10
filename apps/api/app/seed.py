from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .billing import ensure_wallet, grant_signup_credit, seed_price_rules
from .config import Settings
from .models import Resource, User
from .repository import ResourceRepository

SUBSCHOOL_BRAND = {
    "identity": {
        "name": "SubSchool",
        "website": "https://subschool.us",
        "description": "A learning platform where teachers create reusable courses, homework, and tutoring experiences.",
        "category": "Education technology",
        "languages": ["en", "ru"],
        "regions": ["US", "Global"],
    },
    "audiences": {
        "primary": ["Independent teachers", "Tutors"],
        "secondary": ["Students", "Parents", "Course creators"],
    },
    "value_propositions": [
        "Turn teaching expertise into structured learning experiences",
        "Create courses, homework, and tutoring workflows in one place",
    ],
    "tone": {
        "traits": ["clear", "encouraging", "practical", "smart"],
        "prohibited_traits": ["hype-heavy", "patronizing", "guaranteed outcomes"],
    },
    "claims": {
        "allowed": ["Create courses and homework", "Publish reusable learning material"],
        "require_source": ["Learning outcome improvements", "Exam performance"],
        "prohibited": ["Guaranteed income", "Guaranteed scores"],
    },
    "visual": {
        "palette": ["#a24cb8", "#76208a", "#f6f3ee", "#18181b"],
        "logo_assets": [],
        "fonts": ["system-ui"],
        "references": ["kinetic typography", "whiteboard diagrams", "product UI"],
        "forbidden_styles": ["misleading product UI", "real-person clone"],
    },
    "cta": {
        "primary": "Create your first course",
        "alternatives": ["Explore a lesson", "Try the teacher workspace"],
        "target_urls": ["https://subschool.us"],
    },
    "compliance": {
        "high_risk_topics": ["exam guarantees", "children", "income claims"],
        "mandatory_disclosures": ["Synthetic media where required"],
        "age_policy": "Manual review for content depicting minors",
    },
    "source_policy": {
        "trusted_domains": ["subschool.us", "oecd.org", "developers.google.com"],
        "blocked_domains": [],
        "max_source_age_days": 90,
    },
    "confirmed": True,
    "confidence": 0.91,
}


def seed_demo(session: Session) -> None:
    if session.get(Resource, "org_demo"):
        if not session.get(Resource, "membership_demo_owner"):
            ResourceRepository(session).add(
                resource_id="membership_demo_owner",
                kind="membership",
                organization_id="org_demo",
                project_id=None,
                status="active",
                data={"actor_id": "user_demo_owner", "role": "owner", "project_scope": ["*"]},
            )
        return
    repo = ResourceRepository(session)
    repo.add(
        resource_id="org_demo",
        kind="organization",
        organization_id="org_demo",
        project_id=None,
        status="active",
        data={"name": "Bright Frame Studio", "slug": "bright-frame", "timezone": "America/New_York"},
    )
    repo.add(
        resource_id="membership_demo_owner",
        kind="membership",
        organization_id="org_demo",
        project_id=None,
        status="active",
        data={"actor_id": "user_demo_owner", "role": "owner", "project_scope": ["*"]},
    )
    repo.add(
        resource_id="prj_subschool",
        kind="project",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="active",
        data={
            "name": "SubSchool",
            "slug": "subschool",
            "website_url": "https://subschool.us",
            "default_language": "en",
            "regions": ["US"],
            "timezone": "America/New_York",
            "automation_mode": "assisted",
            "autopilot_paused": False,
            "brand_profile_version": 1,
            "settings": {
                "research": {"frequency": "3x weekly", "recency_days": 30, "backlog_target": 7},
                "generation": {"aspect_ratios": ["9:16", "16:9"], "duration": 30, "exploration": 0.2},
                "publishing": {"weekly_cap": 3, "minimum_gap_hours": 18},
                "scoring": {"readiness_manual": 70, "readiness_autopublish": 88, "confidence": 0.65},
                "budget": {"monthly_usd": 120, "used_usd": 24.8},
            },
        },
    )
    repo.add(
        resource_id="brand_subschool_v1",
        kind="brand_profile",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="confirmed",
        data=SUBSCHOOL_BRAND,
    )
    repo.add(
        resource_id="source_subschool_site",
        kind="source",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="healthy",
        data={
            "type": "website",
            "name": "SubSchool website",
            "url": "https://subschool.us",
            "trust_level": "owned",
            "last_checked": datetime.now(UTC).isoformat(),
            "generation_policy": "research_then_approval",
        },
    )
    repo.add(
        resource_id="conn_youtube_demo",
        kind="connection",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="limited",
        data={
            "provider": "youtube",
            "display_name": "SubSchool Demo Channel",
            "external_account_id": "pending_oauth",
            "scopes": ["youtube.upload"],
            "capabilities": ["private_upload", "unlisted_upload", "scheduled_public", "metrics"],
            "mode": "mock",
            "last_successful_request": None,
        },
    )
    repo.add(
        resource_id="strategy_subschool_v1",
        kind="strategy",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="active",
        data={
            "strategy_version": 1,
            "hook_mix": {"question": 0.4, "direct_benefit": 0.3, "contrarian": 0.2, "story": 0.1},
            "duration_mix": {"20_35_sec": 0.7, "36_50_sec": 0.3},
            "visual_mix": {"product_hybrid": 0.5, "motion_graphics": 0.3, "cinematic": 0.2},
            "exploration_rate": 0.2,
            "confidence": 0.34,
            "sample_size": 3,
            "evidence": "Demo observations; not eligible for bounded auto-application.",
        },
    )
    for index, score in enumerate((84, 79, 73), start=1):
        repo.add(
            resource_id=f"idea_seed_{index}",
            kind="idea",
            organization_id="org_demo",
            project_id="prj_subschool",
            status=("ready", "researching", "draft")[index - 1],
            data={
                "title": (
                    "One lesson, three reusable learning assets",
                    "Why feedback works better when it arrives now",
                    "The course-outline mistake teachers can fix today",
                )[index - 1],
                "hook": (
                    "One lesson can do more than you think.",
                    "Late feedback is barely feedback.",
                    "Your outline may be hiding the real outcome.",
                )[index - 1],
                "audience": "Independent teachers",
                "objective": "education",
                "topic_opportunity_score": score,
                "confidence": round(0.74 - index * 0.06, 2),
                "demo_data": True,
            },
        )
    repo.add(
        resource_id="metric_demo_1",
        kind="metric_snapshot",
        organization_id="org_demo",
        project_id="prj_subschool",
        status="complete",
        data={
            "platform": "youtube",
            "window": "7d",
            "captured_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "metrics": {"views": 4210, "likes": 238, "comments": 31, "shares": 74, "average_view_percentage": 68.4},
            "observed_performance_index": 81,
            "availability": {"views": "synthetic_demo", "average_view_percentage": "synthetic_demo"},
            "demo_data": True,
        },
    )


def seed_application(session: Session, settings: Settings) -> None:
    seed_price_rules(session)
    if settings.seed_demo_data or settings.app_auth_mode == "demo":
        seed_demo(session)
        ensure_wallet(session, "org_demo")
        grant_signup_credit(session, "org_demo", "user_demo_owner", 1_000_000)
    email = settings.bootstrap_admin_email.strip().lower()
    if not email:
        return
    user = session.scalar(select(User).where(User.email == email))
    if not user:
        user = User(
            id=f"usr_{secrets.token_hex(12)}",
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            display_name=settings.bootstrap_admin_name,
            status="active",
            email_verified_at=datetime.now(UTC),
            is_platform_admin=True,
        )
        session.add(user)
        session.commit()
    elif not user.is_platform_admin:
        user.is_platform_admin = True
        session.add(user)
        session.commit()
    existing_org = session.get(Resource, "org_demo")
    if not existing_org:
        return
    existing_org.data = {**existing_org.data, "name": "SubSchool", "owner_actor_id": user.id}
    memberships = list(
        session.scalars(select(Resource).where(Resource.kind == "membership", Resource.organization_id == "org_demo"))
    )
    owner = next((item for item in memberships if item.data.get("actor_id") == user.id), None)
    if not owner:
        owner = next((item for item in memberships if item.data.get("actor_id") == "user_demo_owner"), None)
    if owner:
        owner.data = {**owner.data, "actor_id": user.id, "role": "owner", "project_scope": ["*"]}
        owner.status = "active"
        session.add(owner)
    else:
        session.add(
            Resource(
                id=f"mem_{secrets.token_hex(12)}",
                organization_id="org_demo",
                project_id=None,
                kind="membership",
                status="active",
                data={"actor_id": user.id, "role": "owner", "project_scope": ["*"]},
            )
        )
    if settings.app_env == "production":
        legacy_demo_ids = {"conn_youtube_demo", "metric_demo_1", "strategy_subschool_v1"}
        legacy_resources = list(
            session.scalars(select(Resource).where(Resource.organization_id == "org_demo"))
        )
        for resource in legacy_resources:
            is_demo_fixture = (
                resource.id in legacy_demo_ids
                or resource.id.startswith("idea_seed_")
                or bool(resource.data.get("demo_data"))
                or (resource.kind == "connection" and resource.data.get("mode") == "mock")
            )
            if is_demo_fixture:
                session.delete(resource)
    session.add(existing_org)
    session.commit()
    ensure_wallet(session, "org_demo")
    grant_signup_credit(session, "org_demo", user.id, settings.signup_credit_tokens)
