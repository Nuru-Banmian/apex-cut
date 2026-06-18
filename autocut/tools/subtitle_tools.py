"""字幕工具 — 生成和操作字幕文件."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
import pysrt

from autocut.config import settings


@tool
def create_srt(transcript: list[dict], output_path: str) -> dict:
    """根据转写结果生成 SRT 字幕文件。transcript 为 [{start, end, text}, ...] 格式。"""
    if not transcript:
        return {"success": False, "error": "transcript 为空"}

    subs = pysrt.SubRipFile()
    for i, item in enumerate(transcript, 1):
        start_sec = float(item["start"])
        end_sec = float(item["end"])
        text = item.get("text", "").strip()
        if not text:
            continue

        sub = pysrt.SubRipItem(
            index=i,
            start=pysrt.SubRipTime(seconds=start_sec),
            end=pysrt.SubRipTime(seconds=end_sec),
            text=text,
        )
        subs.append(sub)

    path = Path(output_path)
    subs.save(str(path), encoding="utf-8")
    return {"success": True, "subtitle_path": str(path.resolve()), "item_count": len(subs)}


@tool
def merge_subtitle_segments(transcript: list[dict], max_gap: float = 0.5,
                            max_duration: float = 8.0) -> dict:
    """合并相邻的短字幕段，避免字幕过于碎片化。max_gap: 合并间隔阈值（秒）。"""
    if not transcript:
        return {"success": False, "error": "transcript 为空"}

    merged = []
    current = dict(transcript[0])
    for item in transcript[1:]:
        gap = float(item["start"]) - float(current["end"])
        duration = float(item["end"]) - float(current["start"])
        if gap <= max_gap and duration <= max_duration:
            current["end"] = item["end"]
            current["text"] = current.get("text", "") + " " + item.get("text", "")
        else:
            merged.append(current)
            current = dict(item)
    merged.append(current)

    return {"success": True, "merged_transcript": merged, "original_count": len(transcript),
            "merged_count": len(merged)}


# 导出
SUBTITLE_TOOLS = [
    create_srt,
    merge_subtitle_segments,
]
