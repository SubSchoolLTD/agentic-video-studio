from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

from apps.api.app.renderer import render_motion_video, technical_qa


def run_ffmpeg(arguments: list[str]) -> None:
    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for renderer tests")
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
        capture_output=True,
    )


def test_composes_generated_scene_clips_with_voice_audio(tmp_path: Path) -> None:
    clips = []
    for index, color in enumerate(("0x76208a", "0xa24cb8"), start=1):
        path = tmp_path / f"scene_{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=360x640:r=30:d=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ]
        )
        clips.append(path)
    audio = tmp_path / "voice.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4", str(audio)])
    output = tmp_path / "composed.mp4"
    scenes = [
        {"purpose": "hook", "narration": "One lesson can do more.", "on_screen_text": "One useful lesson"},
        {
            "purpose": "SubSchool's payoff: reuse",
            "narration": "Reuse it across formats.",
            "on_screen_text": "Three reusable formats",
        },
    ]

    manifest = render_motion_video(
        title="SubSchool clip composition",
        brand_name="SubSchool",
        scenes=scenes,
        aspect_ratio="9:16",
        duration_seconds=4,
        output_path=output,
        scene_video_paths=clips,
        audio_path=audio,
    )

    assert manifest["scene_video_paths"] == [str(path) for path in clips]
    assert manifest["audio_path"] == str(audio)
    assert manifest["composition_mode"] == "generated_scenes"
    assert manifest["overlay_style"] == "none"
    assert manifest["logo_applied"] is False
    assert manifest["captions_burned_in"] is False
    assert technical_qa(output, aspect_ratio="9:16", duration_target=4)["passed"] is True


def test_optional_overlays_use_uploaded_logo_and_clean_caption_text(tmp_path: Path) -> None:
    clip = tmp_path / "scene.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x205c8a:s=360x640:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ]
    )
    logo = tmp_path / "logo.png"
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=white:s=180x60", "-frames:v", "1", str(logo)])
    audio = tmp_path / "voice.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=2", str(audio)])
    output = tmp_path / "branded.mp4"

    manifest = render_motion_video(
        title="Optional overlays",
        brand_name="This text must never be drawn as a logo",
        scenes=[{"narration": "Readable text without a panel.", "on_screen_text": "Clean caption"}],
        aspect_ratio="9:16",
        duration_seconds=2,
        output_path=output,
        scene_video_paths=[clip],
        audio_path=audio,
        logo_path=logo,
        burn_in_captions=True,
    )

    assert manifest["overlay_style"] == "uploaded_logo+clean_text_captions"
    assert manifest["logo_path"] == str(logo)
    assert manifest["logo_applied"] is True
    assert manifest["captions_burned_in"] is True
    assert technical_qa(output, aspect_ratio="9:16", duration_target=2)["passed"] is True


def test_composes_native_audio_from_each_generated_scene(tmp_path: Path) -> None:
    clips = []
    for index, (color, frequency) in enumerate((("0x205c8a", 330), ("0x4ca278", 440)), start=1):
        path = tmp_path / f"native_scene_{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=360x640:r=30:d=2",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=2",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ]
        )
        clips.append(path)
    output = tmp_path / "native_composed.mp4"

    manifest = render_motion_video(
        title="Native speech composition",
        brand_name="Framewise",
        scenes=[
            {"purpose": "hook", "narration": "Native line one.", "on_screen_text": "Line one"},
            {"purpose": "proof", "narration": "Native line two.", "on_screen_text": "Line two"},
        ],
        aspect_ratio="9:16",
        duration_seconds=4,
        output_path=output,
        scene_video_paths=clips,
        use_scene_audio=True,
    )

    qa = technical_qa(output, aspect_ratio="9:16", duration_target=4)
    assert manifest["audio_mode"] == "scene_native_audio"
    assert manifest["audio_path"] is None
    assert qa["passed"] is True
    assert qa["actual"]["audio_codec"] == "aac"
