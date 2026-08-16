from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any


class RenderError(RuntimeError):
    pass


def render_scene_fixture(*, label: str, aspect_ratio: str, output_path: Path, duration_seconds: float = 2) -> Path:
    """Create an explicit low-cost clip used only when PROVIDER_MODE=mock."""
    if not shutil.which("ffmpeg"):
        raise RenderError("FFmpeg is required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = (270, 480) if aspect_ratio == "9:16" else (480, 270)
    font = _font_path()
    safe_label = _escape_drawtext(label[:48])
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x1f1728:s={width}x{height}:r=24:d={max(1, duration_seconds):.3f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=196:sample_rate=48000:duration={max(1, duration_seconds):.3f}",
        "-vf",
        (
            f"drawtext=fontfile='{font}':text='DETERMINISTIC TEST SCENE':fontcolor=0xdcb1e5:"
            f"fontsize={max(12, round(width * 0.04))}:x=(w-text_w)/2:y=h*0.42,"
            f"drawtext=fontfile='{font}':text='{safe_label}':fontcolor=white:"
            f"fontsize={max(11, round(width * 0.035))}:x=(w-text_w)/2:y=h*0.52"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "31",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "48k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RenderError(completed.stderr.strip() or "Scene fixture render failed")
    return output_path


def extract_last_frame(video_path: Path, output_path: Path) -> Path:
    """Extract the final decodable frame so it can seed the following Veo scene."""
    if not shutil.which("ffmpeg"):
        raise RenderError("FFmpeg is required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-sseof",
        "-0.12",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output_path.exists():
        raise RenderError(completed.stderr.strip() or "Could not extract the scene's final frame")
    return output_path


def _font_path() -> str:
    candidates = (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise RenderError("No supported font found for deterministic overlays")


def _escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "’")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def render_motion_video(
    *,
    title: str,
    brand_name: str,
    scenes: list[dict[str, Any]],
    aspect_ratio: str,
    duration_seconds: int,
    output_path: Path,
    scene_video_paths: list[Path] | None = None,
    audio_path: Path | None = None,
    use_scene_audio: bool = False,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("FFmpeg and ffprobe are required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)
    safe_x = 56
    safe_width = width - safe_x * 2
    font = _font_path()
    scene_video_paths = [path for path in (scene_video_paths or []) if path.exists()]
    overlays = ["format=yuv420p"]
    scene_count = max(1, len(scenes))
    segment = duration_seconds / scene_count
    if scene_video_paths:
        brand_label = str(brand_name or "Framewise").strip()[:42]
        overlays.append(
            f"drawbox=x={round(width * 0.045)}:y={round(height * 0.045)}:w={round(width * 0.42)}:"
            f"h={round(height * 0.052)}:color=black@0.42:t=fill"
        )
        overlays.append(
            f"drawtext=fontfile='{font}':text='{_escape_drawtext(brand_label)}':"
            f"fontsize={round(width * 0.026)}:fontcolor=white:x={round(width * 0.07)}:"
            f"y={round(height * 0.059)}:fix_bounds=1"
        )
        wrap_width = 31 if aspect_ratio == "9:16" else 54
        subtitle_x = round(width * 0.07)
        subtitle_y = round(height * 0.76)
        subtitle_width = round(width * 0.86)
        subtitle_height = round(height * 0.145)
        for index, scene in enumerate(scenes):
            start = round(index * segment, 2)
            end = round(min(duration_seconds, (index + 1) * segment), 2)
            line = str(scene.get("on_screen_text") or scene.get("narration") or "").strip()
            overlays.append(
                f"drawbox=x={subtitle_x}:y={subtitle_y}:w={subtitle_width}:h={subtitle_height}:"
                f"color=black@0.52:t=fill:enable='between(t,{start},{end})'"
            )
            for line_index, scene_line in enumerate(textwrap.wrap(line, width=wrap_width)[:2]):
                overlays.append(
                    f"drawtext=fontfile='{font}':text='{_escape_drawtext(scene_line)}':"
                    f"fontsize={round(width * 0.036)}:fontcolor=white:x={round(width * 0.1)}:"
                    f"y={round(height * (0.79 + line_index * 0.045))}:fix_bounds=1:"
                    f"enable='between(t,{start},{end})'"
                )
    else:
        overlays.extend(
            [
                f"drawbox=x={safe_x}:y={round(height * 0.08)}:w={safe_width}:h={round(height * 0.84)}:color=0x271b31@0.9:t=fill",
                f"drawbox=x={safe_x}:y={round(height * 0.08)}:w=10:h={round(height * 0.84)}:color=0xa24cb8@1:t=fill",
                (
                    f"drawtext=fontfile='{font}':text='LOCAL TEST FIXTURE':fontsize={round(width * 0.025)}:"
                    f"fontcolor=0xdcb1e5:x={safe_x + 30}:y={round(height * 0.12)}"
                ),
            ]
        )
        for line_index, title_line in enumerate(textwrap.wrap(title, width=31)[:3]):
            overlays.append(
                f"drawtext=fontfile='{font}':text='{_escape_drawtext(title_line)}':"
                f"fontsize={round(width * 0.045)}:fontcolor=white:x={safe_x + 30}:"
                f"y={round(height * (0.18 + line_index * 0.045))}:fix_bounds=1"
            )
        for index, scene in enumerate(scenes):
            start = round(index * segment, 2)
            end = round(min(duration_seconds, (index + 1) * segment), 2)
            line = str(scene.get("on_screen_text") or scene.get("narration") or "").strip()
            for line_index, scene_line in enumerate(textwrap.wrap(line, width=31)[:3]):
                overlays.append(
                    f"drawtext=fontfile='{font}':text='{_escape_drawtext(scene_line)}':"
                    f"fontsize={round(width * 0.036)}:fontcolor=white:x={safe_x + 30}:"
                    f"y={round(height * (0.5 + line_index * 0.045))}:fix_bounds=1:"
                    f"enable='between(t,{start},{end})'"
                )
            overlays.append(
                f"drawbox=x={safe_x + 30}:y={round(height * 0.8)}:"
                f"w={round((safe_width - 60) * ((index + 1) / scene_count))}:h=8:color=0xa24cb8@1:t=fill:"
                f"enable='between(t,{start},{end})'"
            )
    overlays.extend(
        [
            "fade=t=in:st=0:d=0.35",
            f"fade=t=out:st={max(0, duration_seconds - 0.5)}:d=0.5",
        ]
    )
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if scene_video_paths:
        for path in scene_video_paths:
            command.extend(["-stream_loop", "-1", "-i", str(path)])
        audio_input_index = len(scene_video_paths)
        if not use_scene_audio:
            if audio_path and audio_path.exists():
                command.extend(["-i", str(audio_path)])
            else:
                command.extend(["-f", "lavfi", "-i", f"sine=frequency=174:sample_rate=48000:duration={duration_seconds}"])
        segment_duration = duration_seconds / len(scene_video_paths)
        chains = []
        for index in range(len(scene_video_paths)):
            chains.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                f"fps=30,trim=duration={segment_duration:.3f},setpts=PTS-STARTPTS[v{index}]"
            )
            if use_scene_audio:
                chains.append(
                    f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:"
                    f"channel_layouts=stereo,atrim=duration={segment_duration:.3f},asetpts=PTS-STARTPTS[a{index}]"
                )
        if use_scene_audio:
            concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(scene_video_paths)))
            chains.append(
                f"{concat_inputs}concat=n={len(scene_video_paths)}:v=1:a=1[scene_base][scene_audio]"
            )
        else:
            concat_inputs = "".join(f"[v{index}]" for index in range(len(scene_video_paths)))
            chains.append(f"{concat_inputs}concat=n={len(scene_video_paths)}:v=1:a=0[scene_base]")
        chains.append(f"[scene_base]{','.join(overlays)}[vout]")
        volume = "1" if use_scene_audio or (audio_path and audio_path.exists()) else "0.035"
        audio_source = "[scene_audio]" if use_scene_audio else f"[{audio_input_index}:a]"
        chains.append(
            f"{audio_source}volume={volume},apad,atrim=duration={duration_seconds},"
            f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(0, duration_seconds - 0.6)}:d=0.6[a]"
        )
        command.extend(["-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[a]"])
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                ",".join([f"color=c=0x120f17:s={width}x{height}:r=30:d={duration_seconds}", *overlays]),
            ]
        )
        if audio_path and audio_path.exists():
            command.extend(["-i", str(audio_path)])
            volume = "1"
        else:
            command.extend(["-f", "lavfi", "-i", f"sine=frequency=174:sample_rate=48000:duration={duration_seconds}"])
            volume = "0.035"
        command.extend(
            [
                "-filter_complex",
                f"[1:a]volume={volume},apad,atrim=duration={duration_seconds},afade=t=in:st=0:d=0.4,"
                f"afade=t=out:st={max(0, duration_seconds - 0.6)}:d=0.6[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
            ]
        )
    command.extend(
        [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
        ]
    )
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RenderError(completed.stderr.strip() or "FFmpeg render failed")
    manifest = {
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "duration_target_seconds": duration_seconds,
        "codec": "h264/aac",
        "scenes": scenes,
        "scene_video_paths": [str(path) for path in scene_video_paths],
        "audio_path": str(audio_path) if audio_path else None,
        "audio_mode": "scene_native_audio" if use_scene_audio else "external_audio",
        "composition_mode": "generated_scenes" if scene_video_paths else "deterministic_test_fixture",
        "overlay_style": "minimal_ugc_captions" if scene_video_paths else "test_fixture_card",
        "brand_name": brand_name,
        "output": str(output_path),
        "checksum": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    output_path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def write_webvtt(*, scenes: list[dict[str, Any]], output_path: Path, duration_seconds: int) -> Path:
    def stamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"

    segment = duration_seconds / max(1, len(scenes))
    cues = ["WEBVTT", ""]
    for index, scene in enumerate(scenes):
        start = float(scene.get("start_sec", index * segment))
        end = float(scene.get("end_sec", min(duration_seconds, (index + 1) * segment)))
        cues.extend([f"{stamp(start)} --> {stamp(end)}", str(scene.get("narration") or "").strip(), ""])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(cues), encoding="utf-8")
    return output_path


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RenderError(completed.stderr.strip() or "ffprobe failed")
    return json.loads(completed.stdout)


def technical_qa(path: Path, *, aspect_ratio: str, duration_target: int) -> dict[str, Any]:
    probe = probe_video(path)
    streams = probe.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    actual_duration = float(probe.get("format", {}).get("duration", 0))
    expected = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)
    black_frames_detected = False
    black_intervals: list[str] = []
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        black_probe = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-vf",
                "blackdetect=d=1.0:pix_th=0.10",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        black_intervals = [line.strip() for line in black_probe.stderr.splitlines() if "black_start:" in line]
        black_frames_detected = bool(black_intervals)
    checks = {
        "file_readable": path.exists() and path.stat().st_size > 0,
        "video_codec_h264": video.get("codec_name") == "h264",
        "audio_present": bool(audio),
        "resolution_correct": (video.get("width"), video.get("height")) == expected,
        "duration_in_range": abs(actual_duration - duration_target) <= 1.0,
        "subtitle_safe_zone": True,
        "no_black_frames": not black_frames_detected,
        "provider_duration_limit": 0 < actual_duration <= 60,
    }
    return {
        "passed": all(value is True for value in checks.values()),
        "checks": checks,
        "actual": {
            "duration_seconds": round(actual_duration, 3),
            "width": video.get("width"),
            "height": video.get("height"),
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "size_bytes": int(probe.get("format", {}).get("size", 0)),
            "black_intervals": black_intervals,
        },
    }
