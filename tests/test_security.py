from __future__ import annotations

import pytest

from apps.api.app.security import validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "gopher://example.com",
        "http://10.0.0.8/private",
    ],
)
def test_ssrf_targets_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_url(url, resolve_dns=False)


def test_public_https_url_is_accepted() -> None:
    assert validate_public_url("https://subschool.us/blog/example", resolve_dns=False).startswith("https://")


def test_cross_tenant_project_is_hidden(client, auth_headers) -> None:
    response = client.get("/v1/projects/prj_subschool", headers={**auth_headers, "X-Organization-ID": "org_other"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_failed"


def test_internal_metrics_runner_requires_google_identity(client) -> None:
    response = client.post("/v1/internal/metrics/collect-due")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Google service identity token required"
