"""剪辑 Agent — 规则引擎确定片段边界，LLM 润色 reason/summary.

流程:
  1. 规则引擎: frame_labels + strategy → 确定片段列表（纯代码，毫秒级）
  2. LLM 润色: 为每个片段写 reason 和整体 summary（可选，失败不影响裁剪）
  3. Reviewer 批准后 → FFmpeg 执行裁剪
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from apex_cut.state import VideoEditState
from apex_cut.config import create_llm, _extract_runtime_keys, OUTPUT_DIR, settings
from apex_cut.tools.video_tools import get_ffmpeg
from apex_cut.errors import check_and_raise
from apex_cut.sse import emit_progress, emit_status


# ═══════════════════════════════════════════════════════════════
# LLM Prompt（只用于润色 reason/summary，不决定片段边界）
# ═══════════════════════════════════════════════════════════════

ANNOTATOR_SYSTEM = """你是 Apex Legends 视频剪辑师。
你的任务很简单：给已确定的片段写标签文字。

## 输入
每个片段已经确定了 start/end 和包含的事件类型。
你只需要用 1-2 句中文描述这个片段值得保留的原因。

## 事件类型说明
- kill: 击杀敌人
- assist: 助攻
- combat: 交火（伤害增加但无击杀）

## 输出 JSON
{
  "annotations": [
    {"index": 1, "reason": "双杀，战斗高潮"},
    {"index": 2, "reason": "单杀，伤害输出高"}
  ],
  "summary": "共 5 段，涵盖 3 次击杀，总时长 120s"
}

只返回 JSON。如果某个片段没有特殊事件，写 "战斗片段"。"""


# ═══════════════════════════════════════════════════════════════
# 规则引擎：纯代码确定片段（主路径，永不失败）
# ═══════════════════════════════════════════════════════════════

def _rule_based_segments(frame_labels: list[dict], duration: float, strategy: dict) -> list[dict]:
    """根据策略参数，从 frame_labels 中机械确定片段边界.

    流程:
      1. 筛选触发帧（匹配 triggers + min_damage 阈值）
      2. 前后 padding
      3. 合并重叠/邻近片段（merge_gap）
      4. 过滤太短的（min_segment）
      5. 排序（chronological / priority）
      6. 超时裁剪（trim_strategy: cut_lowest_priority）
    """
    triggers = strategy.get("triggers", ["kill_occurred", "assist_occurred", "damage_dealt"])
    min_damage = strategy.get("min_damage", 30)
    padding_before = strategy.get("padding_before", 20)
    padding_after = strategy.get("padding_after", 20)
    merge_gap = strategy.get("merge_gap", 8)
    min_segment = strategy.get("min_segment", 3)
    order = strategy.get("order", "chronological")
    priority_weights = strategy.get("priority_weights", {})

    if not frame_labels or duration <= 0:
        return []

    # ── Step 1: 筛选触发帧 ──
    trigger_frames = []
    for f in frame_labels:
        changes = f.get("_changes", {})
        if not changes.get("in_combat"):
            continue

        t = f.get("time_seconds", 0)
        if not t:
            continue

        # 匹配 triggers
        matched = False
        max_score = 0
        events = []

        for trigger in triggers:
            if trigger == "damage_dealt":
                dmg = changes.get("damage_dealt", 0)
                if dmg >= min_damage:
                    matched = True
                    max_score = max(max_score, priority_weights.get("damage_dealt", 1))
                    events.append("combat")
            elif trigger == "kill_occurred" and changes.get("kill_occurred"):
                matched = True
                max_score = max(max_score, priority_weights.get("kill_occurred", 5))
                events.append("kill")
            elif trigger == "assist_occurred" and changes.get("assist_occurred"):
                matched = True
                max_score = max(max_score, priority_weights.get("assist_occurred", 3))
                events.append("assist")

        if matched:
            trigger_frames.append({
                "time": t,
                "score": max_score,
                "events": list(set(events)),
            })

    if not trigger_frames:
        return []

    # ── Step 2: padding → 候选片段 ──
    candidates = []
    for tf in trigger_frames:
        candidates.append({
            "start": round(max(0, tf["time"] - padding_before), 1),
            "end": round(min(duration, tf["time"] + padding_after), 1),
            "score": tf["score"],
            "trigger_time": round(tf["time"], 1),
            "events": tf["events"],
        })

    # ── Step 3: 合并重叠/邻近 ──
    candidates.sort(key=lambda c: c["start"])
    merged = []
    for c in candidates:
        if not merged:
            merged.append(c)
        elif c["start"] - merged[-1]["end"] <= merge_gap:
            merged[-1]["end"] = max(merged[-1]["end"], c["end"])
            merged[-1]["score"] = max(merged[-1]["score"], c["score"])
            merged[-1]["trigger_time"] = round((merged[-1]["trigger_time"] + c["trigger_time"]) / 2, 1)
            # 合并事件
            for evt in c["events"]:
                if evt not in merged[-1]["events"]:
                    merged[-1]["events"].append(evt)
        else:
            merged.append(c)

    # ── Step 4: 过滤太短的 ──
    merged = [m for m in merged if m["end"] - m["start"] >= min_segment]

    if not merged:
        return []

    # ── Step 5: 排序 ──
    if order == "priority":
        merged.sort(key=lambda m: m["score"], reverse=True)

    # ── Step 6: 超时裁剪 ──
    target_duration = strategy.get("_target_duration")  # 由 editor_node 注入
    trim_strategy = strategy.get("trim_strategy", "none")
    if target_duration and trim_strategy == "cut_lowest_priority" and merged:
        total = sum(m["end"] - m["start"] for m in merged)
        if total > target_duration:
            # 按分数升序排列（低分在前），逐个移除直到满足目标（至少保留 1 个）
            merged.sort(key=lambda m: m["score"])  # 低分在前
            while len(merged) > 1:
                total = sum(m["end"] - m["start"] for m in merged)
                if total <= target_duration:
                    break
                merged.pop(0)  # 移除最低分片段
            # 恢复排序
            if order == "priority":
                merged.sort(key=lambda m: m["score"], reverse=True)
            else:
                merged.sort(key=lambda m: m["start"])

    # ── 构建最终方案 ──
    return [
        {
            "start": m["start"],
            "end": m["end"],
            "score": m["score"],
            "trigger_time": m["trigger_time"],
            "reason": "",
            "events": m["events"],
        }
        for m in merged
    ]


# ═══════════════════════════════════════════════════════════════
# LLM 润色：为片段写 reason + summary（可选，失败不影响）
# ═══════════════════════════════════════════════════════════════

def _annotate_segments(segments: list[dict], state: dict) -> tuple[list[dict], str]:
    """用 LLM 为每个片段生成 reason 和整体 summary.

    Returns:
        (annotated_segments, summary_text)
        如果 LLM 失败，返回带默认 reason 的原 segments.
    """
    if not segments:
        return segments, ""

    try:
        provider, api_key, api_base, text_model = _extract_runtime_keys(state)
        llm = create_llm(
            temperature=0.3, runtime_provider=provider,
            runtime_api_key=api_key, runtime_base_url=api_base,
            runtime_model=text_model,
        )

        # 构建简洁的输入
        lines = ["## 已确定的片段"]
        for i, seg in enumerate(segments):
            lines.append(
                f"  [{i+1}] {seg['start']:.0f}s-{seg['end']:.0f}s | "
                f"events={seg.get('events', [])} | score={seg.get('score', 0)}"
            )

        response = llm.invoke([
            SystemMessage(content=ANNOTATOR_SYSTEM),
            HumanMessage(content="\n".join(lines)),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        result = json.loads(content)
        annotations = result.get("annotations", [])
        summary = result.get("summary", "")

        # 合并 reason
        anno_map = {a.get("index", 0): a.get("reason", "") for a in annotations}
        for i, seg in enumerate(segments):
            reason = anno_map.get(i + 1, "")
            if reason:
                seg["reason"] = reason
            elif not seg.get("reason"):
                events = seg.get("events", [])
                seg["reason"] = _default_reason(events)

        print(f"[✂️ 剪辑] LLM 润色: {len(annotations)}/{len(segments)} 个片段, {summary[:80]}")
        return segments, summary

    except Exception as e:
        print(f"[✂️ 剪辑] LLM 润色失败（不影响裁剪）: {e}")
        # 回退：用默认 reason
        for seg in segments:
            if not seg.get("reason"):
                seg["reason"] = _default_reason(seg.get("events", []))
        return segments, ""


def _default_reason(events: list[str]) -> str:
    """根据事件列表生成默认 reason."""
    if not events:
        return "战斗片段"
    if "kill" in events:
        return f"击杀 ({len([e for e in events if e == 'kill'])} 次)"
    if "assist" in events:
        return "助攻"
    return "交火片段"


# ═══════════════════════════════════════════════════════════════
# Editor 节点
# ═══════════════════════════════════════════════════════════════

def editor_node(state: VideoEditState) -> dict:
    """剪辑节点 — 方案模式(规则引擎+LLM润色) or 裁剪模式(FFmpeg)."""
    video_path = state.get("video_path", "")
    requirement = state.get("user_requirement", "")
    review_round = state.get("review_round", 0)
    plan_approved = state.get("plan_approved", False)

    out_dir = Path(state.get("output_dir", OUTPUT_DIR))
    out_dir.mkdir(parents=True, exist_ok=True)

    max_rounds = state.get("max_review_rounds") or settings.max_review_rounds
    force_cut = review_round >= max_rounds

    # ═════════════════════════════════════════════════════════
    # 裁剪模式 — FFmpeg 执行
    # ═════════════════════════════════════════════════════════
    if plan_approved or force_cut:
        if force_cut and not plan_approved:
            msg = "✂️ 超过最大轮次，强制裁剪..."
        else:
            msg = "✂️ 方案通过，执行裁剪..."
        print(f"\n[✂️ 剪辑] {msg}")
        emit_status(msg)
        emit_progress(msg)

        edit_plan = state.get("edit_plan", [])
        target_ar = state.get("target_aspect_ratio")

        if not edit_plan:
            print(f"[✂️ 剪辑] ⚠️ 无方案，回退原视频")
            return {"final_output": video_path, "plan_approved": True}

        output_name = state.get("output_name", "")
        result = _execute_cut(video_path, edit_plan, target_ar, review_round, out_dir, output_name)
        result["plan_approved"] = True  # 裁剪完成 → 路由到 END
        return result

    # ═════════════════════════════════════════════════════════
    # 方案模式 — 规则引擎 + LLM 润色
    # ═════════════════════════════════════════════════════════
    print(f"\n[✂️ 剪辑] 第 {review_round + 1} 轮 — 规则引擎生成方案")
    print(f"[✂️ 剪辑] 需求: {requirement[:120]}")
    emit_status(f"✂️ 分析战斗数据... (第{review_round + 1}轮)")
    emit_progress(f"━━━ ✂️ 剪辑 Agent 第 {review_round + 1} 轮 ━━━")

    probe_info = _get_video_info(video_path)
    total_duration = probe_info["duration"] if probe_info else 0
    target_duration = state.get("target_duration")
    strategy = state.get("segment_strategy") or {}
    frame_labels = state.get("frame_labels", [])

    if not frame_labels:
        print(f"[✂️ 剪辑] ⚠️ 无 frame_labels，回退全片")
        return {
            "edit_plan": [{"start": 0, "end": total_duration, "reason": "无数据，保留全片", "score": 0, "events": []}],
            "review_round": review_round + 1,
        }

    # ── 注入 target_duration 到策略 ──
    if target_duration:
        strategy = dict(strategy)
        strategy["_target_duration"] = target_duration

    # ── 规则引擎：确定片段边界 ──
    segments = _rule_based_segments(frame_labels, total_duration, strategy)
    print(f"[✂️ 剪辑] 规则引擎: {len(segments)} 段")

    # ── LLM 润色：写 reason + summary（首轮执行，后续跳过以省 token）──
    if review_round == 0:
        segments, summary = _annotate_segments(segments, state)
    else:
        summary = ""

    # ── 融入上一轮 Reviewer 反馈 ──
    suggestions = state.get("review_suggestions", "")
    issues = state.get("review_issues", [])
    if suggestions or issues:
        print(f"[✂️ 剪辑] 根据 Reviewer 反馈微调...")
        segments = _apply_review_feedback(segments, suggestions, issues, total_duration)

    # ── 确保边界合法 ──
    edit_plan = []
    for seg in segments:
        start = max(0, seg.get("start", 0))
        end = min(total_duration, seg.get("end", total_duration))
        if end - start >= strategy.get("min_segment", 3):
            edit_plan.append({
                "start": round(start, 1),
                "end": round(end, 1),
                "reason": seg.get("reason", ""),
                "score": seg.get("score", 0),
                "events": seg.get("events", []),
                "trigger_time": seg.get("trigger_time", round((start + end) / 2, 1)),
            })

    if not edit_plan:
        print(f"[✂️ 剪辑] ⚠️ 未产生有效片段，保留全片")
        edit_plan = [{"start": 0, "end": total_duration, "reason": "无有效片段", "score": 0, "events": []}]

    seg_total = sum(s["end"] - s["start"] for s in edit_plan)
    print(f"[✂️ 剪辑] 最终方案: {len(edit_plan)} 段, {seg_total:.1f}s")

    for i, seg in enumerate(edit_plan[:10]):
        print(f"  [{i+1}] {seg['start']:.0f}s-{seg['end']:.0f}s | {seg.get('reason', '')[:80]}")

    if summary:
        emit_progress(f"  📐 {summary}")
    emit_progress(f"  📐 方案: {len(edit_plan)} 段, {seg_total:.0f}s")

    return {
        "edit_plan": edit_plan,
        "review_round": review_round + 1,
    }


def _apply_review_feedback(segments: list[dict], suggestions: str, issues: list[str],
                           duration: float) -> list[dict]:
    """尝试根据 Reviewer 反馈微调片段（简单规则，不用 LLM）."""
    remove_indices = set()
    for issue in issues:
        # ── [遗漏] 15.3s kill: ... → 扩展最近片段去覆盖 ──
        time_match = re.search(r'(\d+\.?\d*)s', str(issue))
        if time_match and issue.startswith("[遗漏]"):
            missing_time = float(time_match.group(1))
            closest = None
            for seg in segments:
                mid = (seg["start"] + seg["end"]) / 2
                if closest is None or abs(mid - missing_time) < abs((closest["start"] + closest["end"]) / 2 - missing_time):
                    closest = seg
            if closest and abs((closest["start"] + closest["end"]) / 2 - missing_time) < 60:
                closest["start"] = min(closest["start"], max(0, missing_time - 20))
                closest["end"] = max(closest["end"], min(duration, missing_time + 20))
                print(f"  🔧 扩展片段覆盖遗漏点 {missing_time}s")
        # ── [误判] 片段 3: ... → 删除对应片段 ──
        if issue.startswith("[误判]"):
            seg_match = re.search(r'片段\s*(\d+)', str(issue))
            if seg_match:
                idx = int(seg_match.group(1)) - 1  # 1-based → 0-based
                if 0 <= idx < len(segments):
                    remove_indices.add(idx)
                    print(f"  🗑️ 移除误判片段 [{idx+1}] {segments[idx]['start']:.0f}s-{segments[idx]['end']:.0f}s")
    if remove_indices:
        segments = [s for i, s in enumerate(segments) if i not in remove_indices]
    return segments


# ═══════════════════════════════════════════════════════════════
# 裁剪执行 — 单次 FFmpeg 合并 + 无损切分独立片段
# ═══════════════════════════════════════════════════════════════

def _execute_cut(video_path: str, edit_plan: list[dict], target_ar: str | None,
                 review_round: int, out_dir: Path, output_name: str = "") -> dict:
    """单次 FFmpeg 合并 → 再无损切分独立片段."""
    probe_info = _get_video_info(video_path)
    total_duration = probe_info["duration"] if probe_info else 0

    if not edit_plan:
        return {"final_output": video_path, "plan_approved": True}

    tool = get_ffmpeg()
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: 一次 FFmpeg 调用输出合并成品 ──
    final_name = f"{output_name}.mp4" if output_name else f"final_merged_round_{review_round}.mp4"
    merged_output = str(out_dir / final_name)
    print(f"[✂️ 剪辑] 🎬 单次裁剪+拼接 {len(edit_plan)} 段 → {Path(merged_output).name}")

    seg_total_dur = sum(s["end"] - s["start"] for s in edit_plan)
    def _trim_progress(pct):
        emit_status(f"✂️ 渲染中... {pct}% ({seg_total_dur:.0f}s 总输出)")

    emit_status(f"✂️ 渲染中... 0% ({seg_total_dur:.0f}s 总输出)")
    trim_result = tool.trim(video_path, edit_plan, merged_output, progress_cb=_trim_progress)
    if not trim_result.get("success"):
        print(f"[✂️ 剪辑] ⚠️ 合并裁剪失败: {trim_result.get('error', '')[:100]}")
        return {"final_output": video_path}

    emit_status(f"✂️ 渲染完成 → 切分片段...")

    # ── Step 2: 从合并成品无损切分独立片段 + 生成缩略图 ──
    clip_files = []
    thumb_files = []
    cumulative_time = 0.0  # 在合并视频中的累计时间
    thumbs_dir = clips_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    for i, seg in enumerate(edit_plan):
        seg_duration = seg["end"] - seg["start"]
        clip_output = str(clips_dir / f"clip_{i+1:03d}_{seg['start']:.0f}s-{seg['end']:.0f}s.mp4")
        thumb_output = str(thumbs_dir / f"thumb_{i+1:03d}.jpg")

        if Path(clip_output).exists() and Path(thumb_output).exists():
            print(f"  [{i+1}/{len(edit_plan)}] ✅ 已存在: {Path(clip_output).name}")
            clip_files.append(clip_output)
            thumb_files.append(thumb_output)
            cumulative_time += seg_duration
            emit_status(f"✂️ 切分中... ({i+1}/{len(edit_plan)})")
            continue

        # -ss -to -c copy 无损切分
        result = tool._run([
            "-ss", str(cumulative_time),
            "-i", merged_output,
            "-to", str(seg_duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            clip_output,
        ], timeout=120)

        if result["success"]:
            size_kb = Path(clip_output).stat().st_size / 1024 if Path(clip_output).exists() else 0
            print(f"  [{i+1}/{len(edit_plan)}] ✅ {Path(clip_output).name} ({size_kb:.0f}KB)")
            clip_files.append(clip_output)

            # 提取缩略图：片段中点的一帧
            thumb_result = tool._run([
                "-ss", str(cumulative_time + seg_duration / 2),
                "-i", merged_output,
                "-vframes", "1",
                "-q:v", "3",
                thumb_output,
            ], timeout=30)
            if thumb_result["success"]:
                thumb_files.append(thumb_output)
            else:
                thumb_files.append("")
            cumulative_time += seg_duration  # 只在成功时推进
        else:
            print(f"  [{i+1}/{len(edit_plan)}] ❌ 切分失败: {result.get('error', '')[:100]}")
            # 不推进 cumulative_time — 失败片段不在合并视频中

        emit_status(f"✂️ 切分中... ({i+1}/{len(edit_plan)})")

    # ── 保存方案清单 ──
    # 直接从成功的 clip_files 构建（而非 zip edit_plan，避免失败片段错位）
    manifest_clips = []
    for i, f in enumerate(clip_files):
        seg = edit_plan[i] if i < len(edit_plan) else {}
        thumb_name = str(Path(thumb_files[i]).name) if i < len(thumb_files) and thumb_files[i] else ""
        manifest_clips.append({
            "index": i + 1,
            "file": str(Path(f).name),
            "thumb": thumb_name,
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "reason": seg.get("reason", ""),
            "score": seg.get("score", 0),
            "events": seg.get("events", []),
        })

    manifest = {
        "video_path": video_path,
        "total_duration": total_duration,
        "target_aspect_ratio": target_ar,
        "review_round": review_round,
        "clips": manifest_clips,
    }
    manifest_path = out_dir / "edit_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)
    print(f"[✂️ 剪辑] 📋 方案清单: {manifest_path}")

    emit_status(f"✅ 裁剪完成: {len(clip_files)} 个片段")
    emit_progress(f"  📦 {len(clip_files)} 个独立片段已保存到 {clips_dir}")

    # ── 复制到结果库 ──
    results_dir = OUTPUT_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    result_name = f"{output_name}.mp4" if output_name else f"result_{Path(video_path).stem}.mp4"
    result_path = results_dir / result_name
    try:
        shutil.copy2(merged_output, result_path)
        print(f"[✂️ 剪辑] 📦 结果已保存: {result_path}")
    except Exception as e:
        print(f"[✂️ 剪辑] ⚠️ 保存结果失败: {e}")

    return {
        "final_output": merged_output,
        "clip_files": clip_files,
        "manifest_path": str(manifest_path),
    }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _get_video_info(video_path: str) -> dict | None:
    try:
        result = get_ffmpeg().probe(video_path)
        return result["info"] if result["success"] else None
    except Exception:
        return None
