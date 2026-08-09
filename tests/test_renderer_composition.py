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
        scenes=scenes,
        aspect_ratio="9:16",
        duration_seconds=4,
        output_path=output,
        scene_video_paths=clips,
        audio_path=audio,
    )

    assert manifest["scene_video_paths"] == [str(path) for path in clips]
    assert manifest["audio_path"] == str(audio)
    assert technical_qa(output, aspect_ratio="9:16", duration_target=4)["passed"] is True
