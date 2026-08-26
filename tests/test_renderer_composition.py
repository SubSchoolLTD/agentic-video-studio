from __future__ import annotations

import re
import subprocess
from pathlib import Path
from shutil import which

from apps.api.app.renderer import prepare_veo_extension_input, probe_video, render_motion_video, technical_qa


def run_ffmpeg(arguments: list[str]) -> None:
    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for renderer tests")
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
        capture_output=True,
    )


def edge_frame_luma(path: Path, *, from_end: bool = False) -> float:
    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for renderer tests")
    seek = ["-sseof", "-0.04"] if from_end else []
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            *seek,
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "signalstats,metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", completed.stderr)
    assert match, completed.stderr
    return float(match.group(1))


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
    assert manifest["edit_style"] == "film_hard_cuts_only"
    assert manifest["overlay_style"] == "none"
    assert manifest["logo_applied"] is False
    assert manifest["captions_burned_in"] is False
    assert manifest["generated_clip_edge_overscan_percent"] == 4
    assert edge_frame_luma(output) > 25
    assert edge_frame_luma(output, from_end=True) > 25
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


def test_normalizes_mixed_scene_sample_aspect_ratios_before_concat(tmp_path: Path) -> None:
    clips = []
    # The exact near-square ratio observed in production can be rounded away by some
    # local encoders. A deliberately non-square second input exercises the same concat
    # contract: heterogeneous scene SARs must be normalized before concatenation.
    for index, sample_aspect_ratio in enumerate(("1/1", "2/1"), start=1):
        path = tmp_path / f"sar_scene_{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x205c8a:s=360x640:r=30:d=1,setsar={sample_aspect_ratio}",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=1",
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

    output = tmp_path / "normalized_sar.mp4"
    manifest = render_motion_video(
        title="Mixed Veo sample aspect ratios",
        brand_name="SubSchool",
        scenes=[
            {"narration": "First scene.", "duration_target": 1},
            {"narration": "Second scene.", "duration_target": 1},
        ],
        aspect_ratio="9:16",
        duration_seconds=2,
        output_path=output,
        scene_video_paths=clips,
        use_scene_audio=True,
    )

    video_stream = next(
        stream for stream in probe_video(output)["streams"] if stream.get("codec_type") == "video"
    )
    assert manifest["generated_clip_sample_aspect_ratio"] == "1:1"
    assert video_stream["sample_aspect_ratio"] == "1:1"
    assert technical_qa(output, aspect_ratio="9:16", duration_target=2)["passed"] is True


def test_prepares_a_rolling_extension_window_without_requiring_audio(tmp_path: Path) -> None:
    source = tmp_path / "cumulative_veo.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x205c8a:s=96x96:r=24:d=31",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    conditioning = tmp_path / "conditioning.mp4"

    prepare_veo_extension_input(source, conditioning)

    duration = float(probe_video(conditioning)["format"]["duration"])
    assert 29.0 <= duration <= 29.6
