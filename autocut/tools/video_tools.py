"""视频处理工具 — 基于 FFmpeg 的底层视频操作.

所有方法返回标准 dict，可直接被 LangChain Function Calling 使用.
设计原则: 无状态 / 容错 / 可组合.
"""

from __future__ import annotations

import subprocess
import json
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from langchain_core.tools import tool

from autocut.config import settings, OUTPUT_DIR


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: str
    audio_channels: int
    audio_sample_rate: int
    bitrate: int
    file_size: int
    has_audio: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def aspect_ratio(self) -> str:
        g = self._gcd(self.width, self.height)
        return f"{self.width // g}:{self.height // g}"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a


# ═══════════════════════════════════════════════════════════
# FFmpeg 引擎
# ═══════════════════════════════════════════════════════════

class FFmpegTool:
    """FFmpeg 命令封装 — Agent 的视频编辑工具箱."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg = ffmpeg_path or settings.ffmpeg_path
        if not shutil.which(self.ffmpeg):
            print(f"⚠️ FFmpeg ('{self.ffmpeg}') 未找到，请安装 FFmpeg 并确保在 PATH 中")

    def _run(self, args: list[str], timeout: int = 3600) -> dict:
        cmd = [self.ffmpeg, "-hide_banner", "-y"] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                return {"success": False, "error": r.stderr.strip()[-500:], "command": " ".join(cmd)}
            return {"success": True, "output": r.stderr.strip(), "command": " ".join(cmd)}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "执行超时", "command": " ".join(cmd)}
        except FileNotFoundError:
            return {"success": False, "error": f"FFmpeg 未找到: {self.ffmpeg}", "command": " ".join(cmd)}

    # ── probe helpers ──────────────────────────────────

    def _probe_with_ffprobe(self, path: Path) -> dict | None:
        """用 ffprobe 获取 JSON 格式的视频信息."""
        probe_cmd = [settings.ffprobe_path, "-v", "quiet", "-print_format", "json",
                      "-show_format", "-show_streams", str(path)]
        try:
            r = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return None
            return json.loads(r.stdout)
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            return None

    def _probe_with_ffmpeg(self, path: Path) -> dict | None:
        """用 ffmpeg -i 解析视频信息（ffprobe 不可用时的 fallback）."""
        import re

        cmd = [self.ffmpeg, "-i", str(path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            stderr = r.stderr
        except Exception:
            return None

        # 从 ffmpeg stderr 中解析流信息
        streams = []
        # 匹配 Duration
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
        duration = 0.0
        if duration_match:
            h, m, s, cs = map(int, duration_match.groups())
            duration = h * 3600 + m * 60 + s + cs / 100.0

        # 匹配视频流 — 用 \b\d{2,5}x\d{2,5}\b 抓分辨率，避免抓到 codec ID (如 0x31637661)
        video_match = re.search(
            r"Stream #(\d+:\d+).*?Video:\s*(\w+).*?\b(\d{2,5})x(\d{2,5})\b.*?\b([\d.]+)\s+fps\b",
            stderr
        )
        if video_match:
            streams.append({
                "codec_type": "video",
                "codec_name": video_match.group(2),
                "width": int(video_match.group(3)),
                "height": int(video_match.group(4)),
                "r_frame_rate": f"{video_match.group(5)}/1",
                "duration": duration,
            })

        # 匹配音频流
        audio_match = re.search(
            r"Stream #(\d+:\d+).*?Audio:\s*(\w+).*?(\d+)\s*Hz.*?,\s*(mono|stereo|\d+)",
            stderr
        )
        channels_map = {"mono": 1, "stereo": 2}
        if audio_match:
            ch_str = audio_match.group(4)
            channels = channels_map.get(ch_str, int(ch_str) if ch_str.isdigit() else 2)
            streams.append({
                "codec_type": "audio",
                "codec_name": audio_match.group(2),
                "channels": channels,
                "sample_rate": audio_match.group(3),
            })

        if not streams:
            return None

        return {
            "streams": streams,
            "format": {"duration": duration, "bit_rate": 0},
        }

    # ── probe ──────────────────────────────────────────

    def probe(self, video_path: str) -> dict:
        path = Path(video_path)
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {video_path}"}

        data = self._probe_with_ffprobe(path)
        if data is None:
            data = self._probe_with_ffmpeg(path)
        if data is None:
            return {"success": False, "error": "无法获取视频信息（ffprobe 和 ffmpeg 都不可用）"}

        video_stream = audio_stream = None
        for s in data.get("streams", []):
            if s["codec_type"] == "video" and video_stream is None:
                video_stream = s
            elif s["codec_type"] == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            return {"success": False, "error": "文件中没有视频轨道"}

        fps_str = video_stream.get("r_frame_rate", "0/1")
        parts = fps_str.split("/")
        try:
            fps = float(parts[0]) / float(parts[1]) if len(parts) == 2 and float(parts[1]) != 0 else float(fps_str)
        except (ValueError, ZeroDivisionError):
            fps = 0.0

        duration = float(data.get("format", {}).get("duration", 0))
        if duration == 0 and "duration" in video_stream:
            duration = float(video_stream["duration"])

        info = VideoInfo(
            path=str(path), duration=duration,
            width=video_stream.get("width", 0), height=video_stream.get("height", 0),
            fps=round(fps, 2), codec=video_stream.get("codec_name", "unknown"),
            audio_codec=audio_stream.get("codec_name", "none") if audio_stream else "none",
            audio_channels=audio_stream.get("channels", 0) if audio_stream else 0,
            audio_sample_rate=int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
            bitrate=int(data.get("format", {}).get("bit_rate", 0)),
            file_size=path.stat().st_size,
            has_audio=audio_stream is not None,
        )
        return {"success": True, "info": info.to_dict()}

    # ── trim ───────────────────────────────────────────

    def trim(self, video_path: str, segments: list[dict], output_path: str) -> dict:
        """裁剪指定片段并拼接."""
        if not segments:
            return {"success": False, "error": "segments 不能为空"}
        if not Path(video_path).exists():
            return {"success": False, "error": f"文件不存在: {video_path}"}

        temp_dir = Path(OUTPUT_DIR) / "temp_trim"
        temp_dir.mkdir(parents=True, exist_ok=True)

        filter_parts = []
        for i, seg in enumerate(segments):
            start, end = float(seg["start"]), float(seg["end"])
            if end <= start:
                return {"success": False, "error": f"片段 {i}: end({end}) <= start({start})"}
            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )

        n = len(segments)
        filter_str = ";".join(filter_parts)
        filter_str += ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv];"
        filter_str += "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[outa]"

        result = self._run([
            "-i", str(Path(video_path)),
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", settings.output_codec, "-crf", str(settings.output_crf),
            "-preset", "medium",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
            result["segments_count"] = n
        return result

    # ── 画幅调整 ───────────────────────────────────────

    def change_resolution(self, video_path: str, width: int, height: int,
                          output_path: str, crop: str = "smart") -> dict:
        """调整分辨率/画幅. crop: smart / center / stretch"""
        if crop == "stretch":
            vf = f"scale={width}:{height}:force_original_aspect_ratio=disable"
        else:
            vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"

        result = self._run([
            "-i", str(Path(video_path)), "-vf", vf,
            "-c:v", settings.output_codec, "-crf", str(settings.output_crf),
            "-preset", "medium", "-c:a", "copy",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
        return result

    # ── 抽帧 ───────────────────────────────────────────

    def extract_frames(self, video_path: str, interval: float = 2.0,
                       output_dir: str = "", max_frames: int = 300) -> dict:
        """等间隔抽帧，用于多模态视觉分析."""
        out = Path(output_dir) if output_dir else OUTPUT_DIR / "frames"
        out.mkdir(parents=True, exist_ok=True)

        info = self.probe(video_path)
        if not info["success"]:
            return info

        actual = min(int(info["info"]["duration"] / interval), max_frames)
        result = self._run([
            "-i", str(Path(video_path)),
            "-vf", f"fps=1/{interval}",
            "-vframes", str(actual),
            str(out / "frame_%04d.jpg"),
        ])
        if result["success"]:
            result["output_dir"] = str(out.resolve())
            result["frame_count"] = actual
        return result

    # ── 音频提取 ───────────────────────────────────────

    def extract_audio(self, video_path: str, output_path: str) -> dict:
        """提取音频轨道为 16kHz 单声道 WAV (适配 Whisper)."""
        result = self._run([
            "-i", str(Path(video_path)),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
        return result

    def replace_audio(self, video_path: str, audio_path: str, output_path: str) -> dict:
        """替换视频的音频轨道."""
        result = self._run([
            "-i", str(Path(video_path)), "-i", str(Path(audio_path)),
            "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
        return result

    # ── 字幕烧录 ───────────────────────────────────────

    def burn_subtitles(self, video_path: str, subtitle_path: str, output_path: str) -> dict:
        """烧录字幕到视频画面（硬字幕）."""
        font = settings.subtitle_font
        size = settings.subtitle_font_size

        if subtitle_path.endswith(".ass"):
            vf = f"ass='{Path(subtitle_path).as_posix()}'"
        else:
            vf = (f"subtitles='{Path(subtitle_path).as_posix()}'"
                  f":force_style='FontName={font},FontSize={size}"
                  f",PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
                  f",BorderStyle=1,Outline=2,Shadow=1'")

        result = self._run([
            "-i", str(Path(video_path)), "-vf", vf,
            "-c:v", settings.output_codec, "-crf", str(settings.output_crf),
            "-preset", "medium", "-c:a", "copy",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
        return result

    # ── 淡入淡出 ───────────────────────────────────────

    def apply_fade(self, video_path: str, output_path: str,
                   fade_in: float = 0.0, fade_out: float = 0.5) -> dict:
        """添加淡入淡出效果."""
        info = self.probe(video_path)
        if not info["success"]:
            return info

        duration = info["info"]["duration"]
        filters = []
        if fade_in > 0:
            filters.append(f"fade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            filters.append(f"fade=t=out:st={duration - fade_out}:d={fade_out}")

        if not filters:
            shutil.copy2(video_path, output_path)
            return {"success": True, "output_path": str(Path(output_path).resolve())}

        result = self._run([
            "-i", str(Path(video_path)), "-vf", ",".join(filters),
            "-c:v", settings.output_codec, "-crf", str(settings.output_crf),
            "-preset", "medium", "-c:a", "copy",
            str(Path(output_path)),
        ])
        if result["success"]:
            result["output_path"] = str(Path(output_path).resolve())
        return result


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_ffmpeg: Optional[FFmpegTool] = None


def get_ffmpeg() -> FFmpegTool:
    global _ffmpeg
    if _ffmpeg is None:
        _ffmpeg = FFmpegTool()
    return _ffmpeg


# ═══════════════════════════════════════════════════════════
# LangChain Tools — Agent 可直接调用
# ═══════════════════════════════════════════════════════════

@tool
def probe_video(video_path: str) -> dict:
    """获取视频文件的完整元信息：时长、分辨率、帧率、编码、音频轨道等。在编辑视频前必须先调用此工具了解素材基本信息。"""
    return get_ffmpeg().probe(video_path)


@tool
def trim_video(video_path: str, segments: list[dict], output_path: str) -> dict:
    """从视频中裁剪指定片段并拼接为成品。segments 为 [{start: 1.5, end: 3.0}, {start: 7.0, end: 10.0}] 格式，单位秒。"""
    return get_ffmpeg().trim(video_path, segments, output_path)


@tool
def change_resolution(video_path: str, width: int, height: int, output_path: str, crop: str = "smart") -> dict:
    """调整视频分辨率/画幅。crop 策略: smart(智能居中裁剪) / center / stretch(拉伸变形)。"""
    return get_ffmpeg().change_resolution(video_path, width, height, output_path, crop)


@tool
def extract_frames(video_path: str, interval: float = 2.0, output_dir: str = "", max_frames: int = 300) -> dict:
    """按固定间隔从视频中抽取关键帧，用于后续多模态视觉分析（如画面内容理解、场景描述）。interval 单位秒。"""
    return get_ffmpeg().extract_frames(video_path, interval, output_dir, max_frames)


@tool
def extract_audio(video_path: str, output_path: str) -> dict:
    """从视频中提取音频轨道，输出 16kHz 单声道 WAV，用于语音转写。"""
    return get_ffmpeg().extract_audio(video_path, output_path)


@tool
def burn_subtitles(video_path: str, subtitle_path: str, output_path: str) -> dict:
    """将字幕文件烧录到视频画面上（硬字幕），支持 .srt 和 .ass 格式。"""
    return get_ffmpeg().burn_subtitles(video_path, subtitle_path, output_path)


@tool
def apply_fade(video_path: str, output_path: str, fade_in: float = 0.0, fade_out: float = 0.5) -> dict:
    """为视频首尾添加淡入淡出效果。fade_in/fade_out 单位秒，0 表示不添加。"""
    return get_ffmpeg().apply_fade(video_path, output_path, fade_in, fade_out)


# 导出所有工具
VIDEO_TOOLS = [
    probe_video,
    trim_video,
    change_resolution,
    extract_frames,
    extract_audio,
    burn_subtitles,
    apply_fade,
]
