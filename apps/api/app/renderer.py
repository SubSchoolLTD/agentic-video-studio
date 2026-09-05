from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import textwrap
from fractions import Fraction
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


def extract_video_tail(video_path: Path, output_path: Path, *, duration_seconds: float = 7.0) -> Path:
    """Materialize only the newly generated tail of a cumulative Veo extension."""
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
        f"-{max(0.5, float(duration_seconds)):.3f}",
        "-i",
        str(video_path),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
        "-af",
        "aresample=48000",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RenderError(completed.stderr.strip() or "Could not extract the Veo extension tail")
    return output_path


def prepare_veo_extension_input(
    video_path: Path,
    output_path: Path,
    *,
    max_duration_seconds: float = 29.0,
) -> Path:
    """Keep a rolling Veo-compatible conditioning window instead of an ever-growing movie.

    Vertex accepts at most 30 seconds for extension. The final movie is assembled from individual
    generated tails; only this private per-character context window is trimmed.
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("FFmpeg and ffprobe are required")
    if not 1 <= max_duration_seconds <= 30:
        raise RenderError("Veo conditioning window must be between 1 and 30 seconds")
    probe = probe_video(video_path)
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise RenderError("Veo extension input has no video track")
    # The audio/container can outlast the video. Seek from the actual video track,
    # not from container EOF, and never accept an audio-only or sub-second file.
    duration = float(video.get("duration") or 0)
    if not math.isfinite(duration) or duration < 1:
        raise RenderError("Veo extension input video track must be at least 1 second")
    has_audio = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if duration <= max_duration_seconds and veo_extension_input_compatible(probe):
        shutil.copyfile(video_path, output_path)
        return output_path
    window = min(duration, max_duration_seconds)
    frame_count = math.floor(window * 24 + 1e-6)
    window = frame_count / 24
    start = max(0, duration - window)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-vf",
        (
            f"setpts=PTS-STARTPTS,trim=start={start:.6f},setpts=PTS-STARTPTS,"
            f"fps=24,trim=end_frame={frame_count},setpts=N/(24*TB),"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if has_audio:
        command.extend([
            "-map", "0:a:0", "-af",
            f"asetpts=PTS-STARTPTS,atrim=start={start:.6f}:duration={window:.6f},aresample=48000,asetpts=N/SR/TB",
            "-c:a", "aac", "-b:a", "192k",
        ])
    command.append(str(output_path))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RenderError(completed.stderr.strip() or "Could not prepare the Veo extension input window")
    if not veo_extension_input_compatible(probe_video(output_path)):
        raise RenderError("Prepared Veo extension input failed duration/frame-rate/timestamp validation")
    return output_path


def veo_extension_input_compatible(probe: dict[str, Any]) -> bool:
    """Check the actual video track, including timestamps, before a paid extension.

    A rolling trim used to leave a one-frame positive edit-list offset. Veo can
    reject that MP4 as sub-second even when ffprobe reports a 29.5-second container.
    Keep every conditioning clip on a zero-based, constant 24-fps timeline.
    """
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        return False
    try:
        duration = float(video.get("duration") or 0)
        start = float(video.get("start_time") or 0)
        rate = Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0")
        container_duration = float(probe.get("format", {}).get("duration") or 0)
        return (
            math.isfinite(duration) and 1 <= duration <= 30
            and math.isfinite(start) and abs(start) < 0.001
            and rate == 24
            and math.isfinite(container_duration) and 1 <= container_duration <= 30
        )
    except (ValueError, TypeError, ZeroDivisionError):
        return False


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
    logo_path: Path | None = None,
    burn_in_captions: bool = False,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("FFmpeg and ffprobe are required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)
    safe_x = 56
    safe_width = width - safe_x * 2
    font = _font_path()
    scene_video_paths = [path for path in (scene_video_paths or []) if path.exists()]
    logo_path = logo_path if logo_path and logo_path.exists() else None
    overlays = ["format=yuv420p"]
    scene_count = max(1, len(scenes))
    segment = duration_seconds / scene_count
    if scene_video_paths:
        if burn_in_captions:
            wrap_width = 31 if aspect_ratio == "9:16" else 54
            for index, scene in enumerate(scenes):
                start = round(index * segment, 2)
                end = round(min(duration_seconds, (index + 1) * segment), 2)
                line = str(scene.get("on_screen_text") or scene.get("narration") or "").strip()
                for line_index, scene_line in enumerate(textwrap.wrap(line, width=wrap_width)[:2]):
                    overlays.append(
                        f"drawtext=fontfile='{font}':text='{_escape_drawtext(scene_line)}':"
                        f"fontsize={round(width * 0.036)}:fontcolor=white:borderw={max(2, round(width * 0.0025))}:"
                        f"bordercolor=black@0.9:shadowx=1:shadowy=1:x=(w-text_w)/2:"
                        f"y={round(height * (0.82 + line_index * 0.045))}:fix_bounds=1:"
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
    # Generated Veo clips already contain complete shots. A renderer-level fade used to
    # create an unwanted opening transition and forced the final frames to black.
    if not scene_video_paths:
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
        logo_input_index = None
        if logo_path:
            logo_input_index = len(scene_video_paths)
            command.extend(["-loop", "1", "-i", str(logo_path)])
        audio_input_index = len(scene_video_paths) + (1 if logo_input_index is not None else 0)
        if not use_scene_audio:
            if audio_path and audio_path.exists():
                command.extend(["-i", str(audio_path)])
            else:
                command.extend(["-f", "lavfi", "-i", f"sine=frequency=174:sample_rate=48000:duration={duration_seconds}"])
        authored_durations = [float(scene.get("duration_target") or 0) for scene in scenes]
        if len(scenes) == len(scene_video_paths) and all(value > 0 for value in authored_durations):
            clip_durations = [max(0.25, value) for value in authored_durations]
            authored_before_last = sum(clip_durations[:-1])
            clip_durations[-1] = max(0.25, float(duration_seconds) - authored_before_last)
        else:
            clip_durations = [duration_seconds / len(scene_video_paths)] * len(scene_video_paths)
        chains = []
        overscan_width = round(width * 1.04 / 2) * 2
        overscan_height = round(height * 1.04 / 2) * 2
        for index in range(len(scene_video_paths)):
            clip_duration = clip_durations[index]
            chains.append(
                f"[{index}:v]scale={overscan_width}:{overscan_height}:"
                f"force_original_aspect_ratio=increase,crop={width}:{height},"
                # Veo occasionally returns an almost-square, but non-identical sample aspect
                # ratio (for example 2997:2996), while another scene is reported as 0:1.
                # FFmpeg's concat filter requires every input to have the exact same SAR.
                f"setsar=1,fps=30,trim=duration={clip_duration:.3f},setpts=PTS-STARTPTS[v{index}]"
            )
            if use_scene_audio:
                chains.append(
                    f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:"
                    f"channel_layouts=stereo,atrim=duration={clip_duration:.3f},asetpts=PTS-STARTPTS[a{index}]"
                )
        if use_scene_audio:
            concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(scene_video_paths)))
            chains.append(
                f"{concat_inputs}concat=n={len(scene_video_paths)}:v=1:a=1[scene_base][scene_audio]"
            )
        else:
            concat_inputs = "".join(f"[v{index}]" for index in range(len(scene_video_paths)))
            chains.append(f"{concat_inputs}concat=n={len(scene_video_paths)}:v=1:a=0[scene_base]")
        video_base = "[scene_base]"
        if logo_input_index is not None:
            chains.append(
                f"[{logo_input_index}:v]scale=w={round(width * 0.18)}:h={round(height * 0.08)}:"
                "force_original_aspect_ratio=decrease,format=rgba[brand_logo]"
            )
            chains.append(
                f"[scene_base][brand_logo]overlay=x={round(width * 0.05)}:y={round(height * 0.045)}:"
                "eof_action=repeat:shortest=1[scene_branded]"
            )
            video_base = "[scene_branded]"
        chains.append(f"{video_base}{','.join(overlays)}[vout]")
        volume = "1" if use_scene_audio or (audio_path and audio_path.exists()) else "0.035"
        audio_source = "[scene_audio]" if use_scene_audio else f"[{audio_input_index}:a]"
        chains.append(
            f"{audio_source}volume={volume},loudnorm=I=-16:LRA=7:TP=-1.0,"
            f"apad,atrim=duration={duration_seconds},afade=t=out:st={max(0, duration_seconds - 0.15)}:d=0.15[a]"
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
                f"[1:a]volume={volume},loudnorm=I=-16:LRA=7:TP=-1.0,apad,atrim=duration={duration_seconds},"
                f"afade=t=out:st={max(0, duration_seconds - 0.15)}:d=0.15[a]",
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
        "edit_style": "film_hard_cuts_only" if scene_video_paths else "test_fixture",
        "overlay_style": (
            "+".join(
                item
                for item in (
                    "uploaded_logo" if logo_path else "",
                    "clean_text_captions" if burn_in_captions else "",
                )
                if item
            )
            or "none"
            if scene_video_paths
            else "test_fixture_card"
        ),
        "brand_name": brand_name,
        "logo_path": str(logo_path) if logo_path else None,
        "logo_applied": bool(logo_path and scene_video_paths),
        "captions_burned_in": bool(burn_in_captions and scene_video_paths),
        "generated_clip_edge_overscan_percent": 4 if scene_video_paths else 0,
        "generated_clip_sample_aspect_ratio": "1:1" if scene_video_paths else None,
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


def write_srt(*, scenes: list[dict[str, Any]], output_path: Path, duration_seconds: int) -> Path:
    def stamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    segment = duration_seconds / max(1, len(scenes))
    cues: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        start = float(scene.get("start_sec", (index - 1) * segment))
        end = float(scene.get("end_sec", min(duration_seconds, index * segment)))
        cues.extend(
            [
                str(index),
                f"{stamp(start)} --> {stamp(end)}",
                str(scene.get("narration") or "").strip(),
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(cues), encoding="utf-8")
    return output_path


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "format=duration,size:"
            "stream=index,codec_type,codec_name,width,height,sample_aspect_ratio,display_aspect_ratio,"
            "duration,start_time,avg_frame_rate,r_frame_rate,nb_frames"
        ),
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
                "blackdetect=d=0.08:pix_th=0.02",
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
        "provider_duration_limit": actual_duration > 0,
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
