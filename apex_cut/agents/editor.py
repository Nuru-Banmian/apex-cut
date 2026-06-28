"""剪辑 Agent — 从 frame_labels 生成片段 → FFmpeg 裁剪.

当前：简单规则（combat 帧 ± 固定 padding，合并重叠）→ FFmpeg 裁剪。
后续：LLM 直接看着 frame_labels + 用户需求 → 决定 edit_plan。
"""

from __future__ import annotations

import json
from pathlib import Path

from apex_cut.state import VideoEditState
from apex_cut.config import OUTPUT_DIR, settings
from apex_cut.tools.video_tools import get_ffmpeg
from apex_cut.sse import emit_progress, emit_status


# ═══════════════════════════════════════════════════════════════
# 片段生成（临时 — 后续 LLM 接管）
# ═══════════════════════════════════════════════════════════════

def _build_segments(frame_labels: list[dict], duration: float) -> list[dict]:
    """从 combat 帧生成片段：每帧 ±8s padding → 合并重叠."""
    PAD_BEFORE = 4
    PAD_AFTER = 4
    MIN_SEGMENT = 3

    if not frame_labels or duration <= 0:
        return []

    # 收集 combat 帧时间
    combat_times = [
        f.get("time_seconds", 0)
        for f in frame_labels
        if f.get("event") == "combat" and f.get("confidence") == "high"
    ]

    if not combat_times:
        return []

    # padding → 候选片段
    candidates = []
    for t in combat_times:
        candidates.append({
            "start": round(max(0, t - PAD_BEFORE), 1),
            "end": round(min(duration, t + PAD_AFTER), 1),
        })

    # 合并重叠/邻接
    candidates.sort(key=lambda c: c["start"])
    merged = []
    for c in candidates:
        if not merged:
            merged.append(c)
        elif c["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], c["end"])
        else:
            merged.append(c)

    # 过滤太短的
    merged = [m for m in merged if m["end"] - m["start"] >= MIN_SEGMENT]

    return [
        {
            "start": m["start"],
            "end": m["end"],
            "reason": "战斗片段",
            "score": 1,
            "events": ["combat"],
        }
        for m in merged
    ]


# ═══════════════════════════════════════════════════════════════
# Editor 节点
# ═══════════════════════════════════════════════════════════════

def editor_node(state: VideoEditState) -> dict:
    """剪辑节点 — 生成片段 + FFmpeg 裁剪."""
    video_path = state.get("video_path", "")
    requirement = state.get("user_requirement", "")

    out_dir = Path(state.get("output_dir", OUTPUT_DIR))
    out_dir.mkdir(parents=True, exist_ok=True)

    probe_info = _get_video_info(video_path)
    total_duration = probe_info["duration"] if probe_info else 0
    frame_labels = state.get("frame_labels", [])

    print(f"\n[️ 剪辑] 生成片段方案...")
    print(f"[️ 剪辑] 需求: {requirement[:120]}")
    emit_status("️ 生成片段...")

    if not frame_labels:
        print(f"[️ 剪辑] ️ 无 frame_labels，回退全片")
        edit_plan = [{"start": 0, "end": total_duration, "reason": "无数据，保留全片", "score": 0, "events": []}]
        return _execute_and_return(video_path, edit_plan, state, out_dir)

    segments = _build_segments(frame_labels, total_duration)
    print(f"[️ 剪辑] {len(segments)} 段")

    if not segments:
        print(f"[️ 剪辑] ️ 无战斗片段，保留全片")
        edit_plan = [{"start": 0, "end": total_duration, "reason": "无战斗片段", "score": 0, "events": []}]
        return _execute_and_return(video_path, edit_plan, state, out_dir)

    edit_plan = []
    for seg in segments:
        start = max(0, seg.get("start", 0))
        end = min(total_duration, seg.get("end", total_duration))
        edit_plan.append({
            "start": round(start, 1),
            "end": round(end, 1),
            "reason": seg.get("reason", "战斗片段"),
            "score": seg.get("score", 1),
            "events": seg.get("events", ["combat"]),
        })

    seg_total = sum(s["end"] - s["start"] for s in edit_plan)
    print(f"[️ 剪辑] 方案: {len(edit_plan)} 段, {seg_total:.1f}s")
    for i, seg in enumerate(edit_plan[:10]):
        print(f"  [{i+1}] {seg['start']:.0f}s-{seg['end']:.0f}s | {seg.get('reason', '')}")

    return _execute_and_return(video_path, edit_plan, state, out_dir)


def _execute_and_return(video_path: str, edit_plan: list[dict], state: dict, out_dir: Path) -> dict:
    """执行 FFmpeg 裁剪并返回结果."""
    target_ar = state.get("target_aspect_ratio")
    output_name = state.get("output_name", "")

    if not edit_plan or len(edit_plan) == 1 and edit_plan[0].get("start") == 0:
        # 单段全片 → 不需要裁剪
        return {"final_output": video_path, "edit_plan": edit_plan}

    tool = get_ffmpeg()
    results_dir = OUTPUT_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    final_name = f"{output_name}.mp4" if output_name else f"{Path(video_path).stem}_cut.mp4"
    result_output = str(results_dir / final_name)
    print(f"[️ 剪辑]  裁剪+拼接 {len(edit_plan)} 段 → {Path(result_output).name}")

    seg_total_dur = sum(s["end"] - s["start"] for s in edit_plan)

    def _trim_progress(pct):
        emit_status(f"️ 渲染中... {pct}% ({seg_total_dur:.0f}s)")

    emit_status(f"️ 渲染中... 0% ({seg_total_dur:.0f}s)")
    trim_result = tool.trim(video_path, edit_plan, result_output, progress_cb=_trim_progress)

    if not trim_result.get("success"):
        err_msg = trim_result.get('error', '')[:200]
        print(f"[️ 剪辑] ️ 裁剪失败: {err_msg}")
        emit_status(f" 裁剪失败: {err_msg[:60]}")
        return {"final_output": video_path, "edit_plan": edit_plan, "error": f"FFmpeg失败: {err_msg}"}

    # manifest
    manifest = {
        "video_path": video_path,
        "total_duration": _get_video_info(video_path).get("duration", 0) if _get_video_info(video_path) else 0,
        "merged_output": result_output,
        "clips": [
            {"index": i + 1, "start": seg["start"], "end": seg["end"],
             "reason": seg.get("reason", ""), "score": seg.get("score", 0),
             "events": seg.get("events", [])}
            for i, seg in enumerate(edit_plan)
        ],
    }
    manifest_path = out_dir / "edit_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    emit_status(f" 裁剪完成 ({seg_total_dur:.0f}s)")
    emit_progress(f"   成品: {Path(result_output).name} ({seg_total_dur:.0f}s)")

    return {
        "final_output": result_output,
        "edit_plan": edit_plan,
        "manifest_path": str(manifest_path),
    }


# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════

def _get_video_info(video_path: str) -> dict | None:
    try:
        result = get_ffmpeg().probe(video_path)
        return result["info"] if result["success"] else None
    except Exception:
        return None
