from __future__ import annotations

import pytest

from apps.mcp.server import automation_configure, project_update_brief, research_run, source_add_text
from apps.mcp.utils import stable_idempotency_key


def test_mcp_idempotency_keys_are_stable_and_bounded() -> None:
    first = stable_idempotency_key("mcp-source", "project", "title", "content")
    second = stable_idempotency_key("mcp-source", "project", "title", "content")
    changed = stable_idempotency_key("mcp-source", "project", "title", "changed")
    assert first == second
    assert first != changed
    assert len(first) < 64


@pytest.mark.asyncio
async def test_mcp_mutating_tools_support_side_effect_free_dry_runs() -> None:
    brief = await project_update_brief("prj", {"automation_mode": "draft_only"}, dry_run=True)
    source = await source_add_text("prj", "Owned lesson", "Source body", True, dry_run=True)
    research = await research_run("prj", "Find evidence about course reuse", dry_run=True)
    assert brief["dry_run"] is True
    assert source["dry_run"] is True
    assert research == {
        "dry_run": True,
        "provider": "parallel",
        "objective": "Find evidence about course reuse",
        "estimated_calls": 1,
    }
    automation = await automation_configure(
        "prj",
        "publish",
        videos_per_week=4,
        selling_percent=20,
        viral_percent=30,
        informative_percent=50,
        dry_run=True,
    )
    assert automation["dry_run"] is True
    assert automation["payload"]["mode"] == "publish"
    assert automation["content_mix_total"] == 100
