from __future__ import annotations


def test_health_and_openapi(client) -> None:
    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["provider_mode"] == "mock"
    schema = client.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.1")
    assert "/v1/projects/{project_id}/generation-jobs" in schema["paths"]
    assert "/v1/publications" in schema["paths"]


def test_observability_smoke_uses_configured_sinks(client, auth_headers) -> None:
    response = client.post(
        "/v1/projects/prj_subschool/observability/smoke",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["event_id"].startswith("evt_")
    assert response.json()["clickhouse_configured"] is False
    assert response.json()["pubsub_configured"] is False


def test_seeded_project_and_brand(client, auth_headers) -> None:
    projects = client.get("/v1/projects", headers=auth_headers)
    assert projects.status_code == 200
    assert any(item["id"] == "prj_subschool" for item in projects.json()["items"])
    brand = client.get("/v1/projects/prj_subschool/brand-profile", headers=auth_headers)
    assert brand.status_code == 200
    assert brand.json()["identity"]["name"] == "SubSchool"


def test_content_ingestion_is_idempotent(client, auth_headers) -> None:
    payload = {
        "project_id": "prj_subschool",
        "external_id": "article_contract_1",
        "type": "article",
        "title": "A reusable lesson contract fixture",
        "url": "https://subschool.us/blog/contract-fixture",
        "content": "Owned fixture about turning a lesson into a reusable module.",
        "rights_confirmed": True,
    }
    headers = {**auth_headers, "Idempotency-Key": "contract-source-1"}
    first = client.post("/v1/content-items", json=payload, headers=headers)
    second = client.post("/v1/content-items", json=payload, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["source_item_id"] == second.json()["source_item_id"]

    changed = {**payload, "title": "Changed title must conflict"}
    conflict = client.post("/v1/content-items", json=changed, headers=headers)
    assert conflict.status_code == 409


def test_api_key_is_only_returned_once(client, auth_headers) -> None:
    created = client.post(
        "/v1/projects/prj_subschool/api-keys",
        json={"name": "Contract client", "scopes": ["projects:read", "generations:read"]},
        headers=auth_headers,
    )
    assert created.status_code == 201
    raw_key = created.json()["key"]
    assert raw_key.startswith("avs_live_")
    listed = client.get("/v1/projects/prj_subschool/api-keys", headers=auth_headers)
    listed_item = next(item for item in listed.json()["items"] if item["id"] == created.json()["id"])
    assert "key" not in listed_item
    assert listed_item["key_prefix"] == raw_key[:18]


def test_tiktok_requires_interactive_consent(client, auth_headers) -> None:
    versions = client.get("/v1/projects/prj_subschool/videos", headers=auth_headers).json()["items"]
    if not versions:
        return
    version_id = versions[0]["versions"][0]["id"]
    response = client.post(
        "/v1/publications",
        json={
            "video_version_id": version_id,
            "connection_id": "unconfigured_tiktok",
            "platform": "tiktok",
            "title": "A compliant draft",
            "privacy": "public",
            "dry_run": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
