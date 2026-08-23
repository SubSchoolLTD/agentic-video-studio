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


def test_veo_extension_uses_previous_video_and_materializes_only_new_tail(client, monkeypatch, tmp_path) -> None:
    captured = {}
    generated_video = SimpleNamespace(video=SimpleNamespace(video_bytes=b"cumulative-veo-video"))
    operation = SimpleNamespace(
        done=True,
        error=None,
        response=SimpleNamespace(generated_videos=[generated_video]),
    )

    def generate_videos(**kwargs):
        captured.update(kwargs)
        return operation

    fake_client = SimpleNamespace(
        models=SimpleNamespace(generate_videos=generate_videos),
        operations=SimpleNamespace(get=lambda value: value),
    )
    monkeypatch.setattr(providers, "google_genai_client", lambda settings: fake_client)

    def fake_extract(cumulative, tail, *, duration_seconds):
        assert cumulative.read_bytes() == b"cumulative-veo-video"
        assert duration_seconds == 7.0
        tail.write_bytes(b"new-seven-second-tail")
        return tail

    monkeypatch.setattr(providers, "extract_video_tail", fake_extract)
    output = tmp_path / "scene_2.mp4"
    cumulative = tmp_path / "scene_2_continuation.mp4"

    result = client.app.state.workflow.veo._generate(
        "Continue the same creator and voice",
        "9:16",
        output,
        True,
        None,
        None,
        7,
        42,
        "gs://private/scene_1_continuation.mp4",
        cumulative,
    )

    assert result == output
    assert output.read_bytes() == b"new-seven-second-tail"
    assert captured["video"].uri == "gs://private/scene_1_continuation.mp4"
    assert captured["image"] is None
    assert captured["config"].duration_seconds is None
