from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.app import providers


def test_veo_empty_success_response_is_a_retryable_provider_error(client, monkeypatch, tmp_path) -> None:
    operation = SimpleNamespace(done=True, error=None, response=SimpleNamespace(generated_videos=None))
    fake_client = SimpleNamespace(
        models=SimpleNamespace(generate_videos=lambda **kwargs: operation),
        operations=SimpleNamespace(get=lambda value: value),
    )
    monkeypatch.setattr(providers, "google_genai_client", lambda settings: fake_client)

    with pytest.raises(RuntimeError, match="Veo completed without generated video output"):
        client.app.state.workflow.veo._generate(
            "A safe creator shot",
            "9:16",
            tmp_path / "scene.mp4",
            True,
            None,
            None,
            6,
            42,
        )
