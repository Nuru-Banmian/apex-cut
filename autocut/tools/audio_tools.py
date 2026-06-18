"""音频分析工具 — Whisper 语音转写 + 音频特征分析."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from autocut.config import settings, OUTPUT_DIR, MODEL_DIR
from autocut.tools.video_tools import get_ffmpeg


@tool
def transcribe_audio(video_path: str, language: str = "zh") -> dict:
    """将视频中的语音转写为带时间戳的文本。language 参数: zh(中文) / en(英文) / auto(自动检测)。
    返回 [{start, end, text, confidence}, ...] 格式的转写结果。"""
    _ensure_faster_whisper()

    # 1. 提取音频
    audio_path = Path(OUTPUT_DIR) / "temp_audio.wav"
    result = get_ffmpeg().extract_audio(video_path, str(audio_path))
    if not result["success"]:
        return result

    # 2. 转写
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=str(MODEL_DIR),
        )
        lang = None if language == "auto" else language
        segments, info = model.transcribe(str(audio_path), language=lang, beam_size=5)

        transcript = []
        for seg in segments:
            transcript.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
                "confidence": round(seg.avg_logprob, 4),
                "speaker": "",
            })
        return {
            "success": True,
            "transcript": transcript,
            "language": info.language,
            "language_probability": round(info.language_probability, 4),
            "segment_count": len(transcript),
        }
    except ImportError:
        return {"success": False, "error": "faster-whisper 未安装，请运行 pip install faster-whisper"}
    except Exception as e:
        return {"success": False, "error": f"转写失败: {e}"}


@tool
def detect_silence(video_path: str, threshold_db: float = -40.0,
                   min_silence_duration: float = 1.0) -> dict:
    """检测视频中的静音片段。threshold_db: 静音判定阈值（dB），越负越严格。
    min_silence_duration: 最短静音判定时长（秒）。
    返回 [{start, end, duration}, ...] 格式的静音区间列表。"""
    from pydub import AudioSegment
    from pydub.silence import detect_silence as pydub_detect_silence

    audio_path = Path(OUTPUT_DIR) / "temp_silence.wav"
    result = get_ffmpeg().extract_audio(video_path, str(audio_path))
    if not result["success"]:
        return result

    try:
        audio = AudioSegment.from_file(str(audio_path))
        silences = pydub_detect_silence(
            audio,
            min_silence_len=int(min_silence_duration * 1000),
            silence_thresh=threshold_db,
        )
        silence_list = [
            {"start": round(s[0] / 1000, 2), "end": round(s[1] / 1000, 2),
             "duration": round((s[1] - s[0]) / 1000, 2)}
            for s in silences
        ]
        return {"success": True, "silences": silence_list, "count": len(silence_list)}
    except ImportError:
        return {"success": False, "error": "pydub 未安装，请运行 pip install pydub"}
    except Exception as e:
        return {"success": False, "error": f"静音检测失败: {e}"}


@tool
def analyze_audio_energy(video_path: str) -> dict:
    """分析视频的音频能量（音量）变化，用于识别高能片段。返回每秒的 RMS 能量值列表。"""
    import numpy as np

    audio_path = Path(OUTPUT_DIR) / "temp_energy.wav"
    result = get_ffmpeg().extract_audio(video_path, str(audio_path))
    if not result["success"]:
        return result

    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=None)
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]

        # 按秒聚合
        frames_per_sec = sr / 512
        energy_per_sec = []
        for i in range(0, len(rms), int(frames_per_sec)):
            chunk = rms[i:i + int(frames_per_sec)]
            energy_per_sec.append(round(float(np.mean(chunk)), 6))

        # 找出高能时刻（超过均值 1.5 倍标准差）
        mean_e = np.mean(energy_per_sec)
        std_e = np.std(energy_per_sec)
        peaks = [
            {"time": i, "energy": e}
            for i, e in enumerate(energy_per_sec) if e > mean_e + 1.5 * std_e
        ]

        return {
            "success": True,
            "energy_per_second": energy_per_sec,
            "duration_seconds": len(energy_per_sec),
            "mean_energy": round(float(mean_e), 6),
            "peak_times": peaks,
            "peak_count": len(peaks),
        }
    except ImportError:
        return {"success": False, "error": "librosa 未安装，请运行 pip install librosa"}
    except Exception as e:
        return {"success": False, "error": f"音频能量分析失败: {e}"}


def _ensure_faster_whisper():
    """确保 faster-whisper 可用."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        pass  # 工具调用时会给出友好提示


# 导出
AUDIO_TOOLS = [
    transcribe_audio,
    detect_silence,
    analyze_audio_energy,
]
