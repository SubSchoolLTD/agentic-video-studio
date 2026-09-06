"""Backfill idea stages from their current production. Media is never modified.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    resources = sa.table(
        "resources",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("status", sa.String),
        sa.column("organization_id", sa.String),
        sa.column("project_id", sa.String),
        sa.column("data", sa.JSON),
    )
    connection = op.get_bind()
    rows = {
        row["id"]: row
        for row in connection.execute(
            sa.select(resources).where(
                resources.c.kind.in_(["idea", "generation_job", "video", "publication"])
            )
        ).mappings()
    }
    published = {
        (row["organization_id"], row["project_id"], row["data"].get("video_version_id"))
        for row in rows.values()
        if row["kind"] == "publication" and row["status"] == "published"
    }
    for idea in rows.values():
        if idea["kind"] != "idea":
            continue
        status = "selected"
        scope = (idea["organization_id"], idea["project_id"])
        job = rows.get(idea["data"].get("generation_job_id"))
        if job and job["kind"] == "generation_job" and (job["organization_id"], job["project_id"]) == scope:
            if job["status"] not in {"ready", "cancelled"}:
                status = (
                    "video_generation"
                    if job["data"].get("current_stage")
                    in {"scene_generation", "voice_audio", "render", "qa", "scoring", "completed"}
                    else "script_generation"
                )
            else:
                video = rows.get(job["data"].get("video_id"))
                if (
                    video
                    and video["kind"] == "video"
                    and (video["organization_id"], video["project_id"]) == scope
                ):
                    status = (
                        "published"
                        if any(
                            (*scope, version_id) in published
                            for version_id in (
                                job["data"].get("video_version_ids")
                                or [video["data"].get("latest_version_id")]
                            )
                        )
                        else "video_ready"
                    )
                elif job["status"] == "ready":
                    status = "video_ready"
        connection.execute(sa.update(resources).where(resources.c.id == idea["id"]).values(status=status))


def downgrade() -> None:
    # Legacy labels cannot reconstruct an editorial decision; map without touching content.
    resources = sa.table("resources", sa.column("kind", sa.String), sa.column("status", sa.String))
    op.execute(
        sa.update(resources)
        .where(resources.c.kind == "idea")
        .values(
            status=sa.case(
                (resources.c.status == "selected", "draft"),
                else_="planned",
            )
        )
    )
