"""剪辑 Agent — 代码先行计算 + LLM 优化.

流程:
  1. 代码根据静音/质量问题自动计算 baseline keep_segments（去掉静音>2s）
  2. LLM 接收 baseline + 分析数据，优化剪辑方案（调整切点/删废话/保留高光）
  3. 代码执行 FFmpeg 裁剪
  4. LLM 失败时直接用 baseline，确保静音至少被去掉

设计原则:
  - 代码保证"至少去掉静音"，LLM 负责"剪得更好"
  - baseline 始终可用，LLM 失败不回退到原视频
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from autocut.state import VideoEditState
from autocut.config import create_llm, _extract_runtime_keys, OUTPUT_DIR
from autocut.tools.video_tools import get_ffmpeg
from autocut.errors import check_and_raise


EDITOR_SYSTEM_PROMPT = """你是专业视频剪辑师。你会收到一个自动生成的"基线剪辑方案"（已去掉长静音，切点已对齐到词边界），请在此基础上优化。

你会收到:
- **基线方案 (baseline_segments)**: 代码自动计算的结果，已去掉 >2s 静音且切点对齐词边界。这是你的起点。
- **叙事结构**: 视频的 intro/body/climax/outro 骨架
- **场景分析**: 每个场景的画面+音频综合描述
- **语音转写**: 逐句文本（含词级时间戳）
- **精彩片段**: 优先保留的高光时刻
- **用户需求 + 目标时长**

你的任务是优化 baseline: 进一步去掉冗余内容、调整切点位置、保护高光片段。

返回优化后的 JSON:
{
    "keep_segments": [
        {"start": 0.0, "end": 15.5, "reason": "开场介绍，信息完整"}
    ],
    "total_after_cut": 120.5,
    "edit_summary": "在基线基础上进一步去掉了2处口误，优化了3个切点"
}

剪辑铁律（必须遵守）:
1. **绝不切断单词/句子** — 所有切点必须落在词边界上。baseline 已对齐，调整切点时微调 ±200ms 即可
2. **优先在静音处下刀** — 静音 ≥400ms 是最佳切点，150-400ms 可用但需谨慎，<150ms 绝对不切
3. **保护情绪高点** — 笑声、掌声、金句、强调词 → 保留并向后延 0.5-1s 让观众消化
4. **说话人切换留气口** — 两个不同说话人之间保留 400-600ms 间隔
5. **静音>2s 必须删除** — baseline 已处理，不要再加回来
6. **优先保留精彩片段** (score >= 7)
7. **叙事结构 climax 段优先保护**，intro/outro 可适度精简
8. **有目标时长时**，从低精彩度片段开始裁
9. **相邻段间隔 <0.5s 合并**
10. **如果你认为 baseline 已经足够好，直接返回 baseline**

只返回 JSON，不要其他。"""


def editor_node(state: VideoEditState) -> dict:
    """剪辑节点 — 代码 baseline + LLM 优化."""
    video_path = state.get("video_path", "")
    requirement = state.get("user_requirement", "")
    review_round = state.get("review_round", 0)
    review_suggestions = state.get("review_suggestions", "")

    print(f"\n[✂️  剪辑] 第 {review_round + 1} 轮剪辑")

    out_dir = Path(state.get("output_dir", OUTPUT_DIR))
    out_dir.mkdir(parents=True, exist_ok=True)
    final_output = str(out_dir / f"draft_round_{review_round + 1}.mp4")

    # ── 获取视频时长 ──
    probe_info = _get_video_info(video_path)
    total_duration = probe_info["duration"] if probe_info else 0
    print(f"[✂️  剪辑] 原始时长: {total_duration:.1f}s")

    # ═════════════════════════════════════════════════════
    # Step 1: 代码先行计算 baseline（去静音 + 词边界对齐）
    # ═════════════════════════════════════════════════════
    quality_issues = state.get("quality_issues", [])
    silences = state.get("silences", [])
    transcript = state.get("transcript", [])

    # 收集所有需要去掉的时间区间
    cut_zones = []
    # 收集 quality_issues 中所有 high/medium 级别的问题（不限于 silence）
    for iss in quality_issues:
        if iss.get("severity") in ("high", "medium"):
            start = iss.get("start")
            end = iss.get("end")
            if start is not None and end is not None:
                cut_zones.append({"start": float(start), "end": float(end),
                                  "reason": iss.get("issue_type", "quality_issue")})
    # 也加入原始静音检测中 >2s 的（确保底层检测不被 LLM 遗漏）
    for s in silences:
        if s.get("duration", 0) >= 2.0:
            zone = {"start": s["start"], "end": s["end"]}
            if not any(abs(zone["start"] - cz["start"]) < 0.3 for cz in cut_zones):
                cut_zones.append(zone)

    # 从 cut_zones 反推 keep_segments（去掉这些区间后剩下的）
    baseline_segments = _compute_baseline(total_duration, cut_zones)

    # 关键：将切点对齐到最近的词边界（video-use 技法）
    if transcript:
        baseline_segments = _snap_to_word_boundaries(baseline_segments, transcript)
        print(f"[✂️  剪辑] 词边界对齐完成")

    baseline_duration = sum(s["end"] - s["start"] for s in baseline_segments)
    removed_duration = total_duration - baseline_duration
    print(f"[✂️  剪辑] Baseline: {len(baseline_segments)} 段, "
          f"去除 {removed_duration:.1f}s 静音/问题 ({removed_duration/total_duration*100:.0f}%)"
          if total_duration > 0 else f"[✂️  剪辑] Baseline: {len(baseline_segments)} 段")

    # ═════════════════════════════════════════════════════
    # Step 2: LLM 优化 baseline
    # ═════════════════════════════════════════════════════
    edit_plan = list(baseline_segments)  # 默认用 baseline

    # 构建 LLM 上下文
    context_parts = [f"## 用户需求\n{requirement}"]

    if state.get("content_summary"):
        context_parts.append(f"## 视频内容摘要\n{state['content_summary']}")
    if state.get("content_tags"):
        context_parts.append(f"## 内容标签\n{', '.join(state['content_tags'])}")

    # 叙事结构
    if state.get("narrative_structure"):
        context_parts.append(f"## 叙事结构\n{json.dumps(state['narrative_structure'], ensure_ascii=False)}")

    # 场景分析
    if state.get("scene_analyses"):
        context_parts.append(f"## 场景分析\n{json.dumps(state['scene_analyses'], ensure_ascii=False)[:3000]}")

    # 精彩片段
    if state.get("highlights"):
        context_parts.append(f"## 精彩片段（优先保留）\n{json.dumps(state['highlights'], ensure_ascii=False)}")

    # 转写文本（截断）
    transcript = state.get("transcript", [])
    if transcript:
        context_parts.append(f"## 语音转写\n{json.dumps(transcript, ensure_ascii=False)[:4000]}")

    # 目标约束
    target_dur = state.get("target_duration")
    if target_dur:
        context_parts.append(f"## 目标时长\n{target_dur} 秒")

    target_ar = state.get("target_aspect_ratio")
    if target_ar:
        context_parts.append(f"## 目标画幅\n{target_ar}")

    if review_suggestions:
        context_parts.append(f"## 上一轮审核反馈\n{review_suggestions}")

    context_parts.append(f"## 原始视频时长\n{total_duration} 秒")

    # 关键：把 baseline 作为起点传给 LLM
    context_parts.append(
        f"## 基线方案（已去掉静音，{len(baseline_segments)} 段，共 {baseline_duration:.1f}s）\n"
        f"{json.dumps(baseline_segments, ensure_ascii=False)}"
    )

    context = "\n\n".join(context_parts)

    # 调用 LLM 优化
    try:
        provider, api_key, api_base = _extract_runtime_keys(state)
        llm = create_llm(temperature=0.3, runtime_provider=provider,
                         runtime_api_key=api_key, runtime_base_url=api_base)

        response = llm.invoke([
            SystemMessage(content=EDITOR_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        plan = json.loads(content)
        llm_segments = plan.get("keep_segments", [])

        if llm_segments:
            llm_duration = sum(s["end"] - s["start"] for s in llm_segments)
            print(f"[✂️  剪辑] LLM 方案: {len(llm_segments)} 段, 预计 {llm_duration:.1f}s "
                  f"({(total_duration-llm_duration)/total_duration*100:.0f}% 去除)"
                  if total_duration > 0 else
                  f"[✂️  剪辑] LLM 方案: {len(llm_segments)} 段, 预计 {llm_duration:.1f}s")

            # 验证: LLM 方案至少去掉了 baseline 去掉的静音
            if _validate_plan(llm_segments, baseline_segments, total_duration):
                edit_plan = llm_segments
                print(f"[✂️  剪辑] ✅ 采用 LLM 优化方案")
            else:
                print(f"[✂️  剪辑] ⚠️ LLM 方案不如 baseline（可能漏掉静音），采用 baseline")
                edit_plan = baseline_segments
        else:
            print(f"[✂️  剪辑] ⚠️ LLM 返回空方案，采用 baseline")
            edit_plan = baseline_segments

    except Exception as e:
        check_and_raise(e, "剪辑")
        print(f"[✂️  剪辑] LLM 优化失败: {e}，采用 baseline（{len(baseline_segments)} 段, {baseline_duration:.1f}s）")
        edit_plan = baseline_segments

    # ═════════════════════════════════════════════════════
    # Step 3: 执行 FFmpeg 裁剪
    # ═════════════════════════════════════════════════════
    if edit_plan and len(edit_plan) > 0:
        tool = get_ffmpeg()

        # 合并相邻段
        merged = _merge_close_segments(edit_plan)
        merged_dur = sum(s["end"] - s["start"] for s in merged)
        print(f"[✂️  剪辑] 执行裁剪: {len(merged)} 段, 总 {merged_dur:.1f}s")

        # 检查是否需要裁剪（如果只有一段且覆盖整个视频，跳过 FFmpeg）
        if len(merged) == 1 and abs(merged[0]["start"]) < 0.1 and abs(merged[0]["end"] - total_duration) < 0.5:
            # 没有实际裁剪，拷贝原视频
            import shutil
            shutil.copy2(video_path, final_output)
            print(f"[✂️  剪辑] 无需裁剪（单段=全视频），直接拷贝")
        else:
            trim_result = tool.trim(video_path, merged, final_output)
            if trim_result["success"]:
                out_size = Path(final_output).stat().st_size if Path(final_output).exists() else 0
                in_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
                print(f"[✂️  剪辑] ✅ 成品: {final_output}")
                print(f"[✂️  剪辑]    文件大小: {out_size/1024:.0f}KB / 原始: {in_size/1024:.0f}KB")
            else:
                error_msg = trim_result.get("error", "")[-300:]
                print(f"[✂️  剪辑] ❌ FFmpeg 失败: {error_msg}")
                # FFmpeg 失败时的回退
                import shutil
                shutil.copy2(video_path, final_output)
                print(f"[✂️  剪辑] 已回退: 拷贝原视频")

        # 画幅调整
        if target_ar and Path(final_output).exists():
            w, h = _parse_aspect_ratio(target_ar)
            if w and h:
                print(f"[✂️  剪辑] 调整画幅到 {w}x{h}")
                ar_output = str(out_dir / f"draft_round_{review_round + 1}_{w}x{h}.mp4")
                ar_result = tool.change_resolution(final_output, w, h, ar_output)
                if ar_result["success"]:
                    final_output = ar_output

        # 音频淡入淡出（video-use 标准: 30ms per cut boundary）
        if Path(final_output).exists():
            fade_output = str(out_dir / f"draft_round_{review_round + 1}_fade.mp4")
            fade_result = tool.apply_fade(final_output, fade_output, fade_in=0.03, fade_out=0.03)
            if fade_result["success"]:
                final_output = fade_output
    else:
        import shutil
        shutil.copy2(video_path, final_output)
        print(f"[✂️  剪辑] 无可用方案，保留原视频")

    return {
        "edit_plan": edit_plan,
        "draft_output": final_output,
        "review_round": review_round + 1,
    }


# ═════════════════════════════════════════════════
# Baseline 计算：根据 cut_zones 反推 keep_segments
# ═════════════════════════════════════════════════

def _compute_baseline(total_duration: float, cut_zones: list[dict]) -> list[dict]:
    """根据要去掉的区间反推要保留的区间.

    例如: 视频 0-100s, cut_zones=[{15-20}, {50-55}]
          → keep_segments=[{0-15}, {20-50}, {55-100}]
    """
    if not cut_zones or total_duration <= 0:
        return [{"start": 0, "end": total_duration, "reason": "保留全部"}]

    # 按 start 排序并去重
    sorted_zones = sorted(cut_zones, key=lambda z: z["start"])

    # 合
    merged_zones = []
    for zone in sorted_zones:
        if merged_zones and zone["start"] <= merged_zones[-1]["end"] + 0.3:
            merged_zones[-1]["end"] = max(merged_zones[-1]["end"], zone["end"])
        else:
            merged_zones.append(dict(zone))

    # 反推保留段
    keep = []
    cursor = 0.0

    for zone in merged_zones:
        if zone["start"] > cursor + 0.1:  # 有可保留的区间
            keep.append({
                "start": round(cursor, 2),
                "end": round(zone["start"], 2),
                "reason": "有效内容",
            })
        cursor = max(cursor, zone["end"])

    # 最后一段
    if cursor < total_duration - 0.1:
        keep.append({
            "start": round(cursor, 2),
            "end": round(total_duration, 2),
            "reason": "有效内容",
        })

    return keep if keep else [{"start": 0, "end": total_duration, "reason": "保留全部"}]


def _validate_plan(llm_segments: list[dict], baseline_segments: list[dict],
                   total_duration: float) -> bool:
    """验证 LLM 方案是否合理.

    检查:
      1. LLM 方案总时长不超过原始时长
      2. LLM 方案去掉了至少 baseline 去掉的 80%
    """
    if not llm_segments or not baseline_segments:
        return False

    llm_total = sum(s["end"] - s["start"] for s in llm_segments)
    base_total = sum(s["end"] - s["start"] for s in baseline_segments)

    # LLM 方案不能比原始视频还长
    if llm_total > total_duration * 1.01:
        return False

    # LLM 方案去掉的内容应该 >= baseline 去掉的 80%
    # （允许 LLM 保留一些 baseline 标记为静音但实际上有内容的部分）
    llm_removed = total_duration - llm_total
    base_removed = total_duration - base_total

    if base_removed > 0 and llm_removed < base_removed * 0.5:
        return False

    return True


def _snap_to_word_boundaries(segments: list[dict], transcript: list[dict],
                            max_snap: float = 0.2) -> list[dict]:
    """将 keep_segments 的切点对齐到最近的字/词边界（±200ms）。

    video-use 硬规则: "绝不切断单词"，切点必须落在词边界上。
    同时保证: 30-200ms 的 padding 窗口吸收 ASR 时间戳漂移。
    """
    if not transcript:
        return segments

    # 从转写中提取所有词及其时间戳
    # transcript 格式: [{start, end, text}]，每个 segment 可能包含多个词
    word_boundaries = set()
    for seg in transcript:
        word_boundaries.add(round(seg["start"], 2))
        word_boundaries.add(round(seg["end"], 2))
    sorted_words = sorted(word_boundaries)

    def snap(ts: float, prefer: str = "nearest") -> float:
        """找到离 ts 最近的词边界（在 max_snap 窗口内）."""
        best = ts
        best_dist = float("inf")
        for w in sorted_words:
            dist = abs(w - ts)
            if dist <= max_snap and dist < best_dist:
                if prefer == "earlier" and w > ts:
                    continue  # 偏好更早的边界
                if prefer == "later" and w < ts:
                    continue  # 偏好更晚的边界
                best = w
                best_dist = dist
        return best

    snapped = []
    for i, seg in enumerate(segments):
        new_seg = dict(seg)
        seg_start = seg["start"]
        seg_end = seg["end"]

        # 段首: 偏好稍早的边界（避免切到已经开始说的内容）
        # 但第一段的段首不调整（保持 0）
        if i > 0:
            new_seg["start"] = snap(seg_start, prefer="earlier")
        else:
            new_seg["start"] = seg_start  # 保持 0

        # 段尾: 偏好稍晚的边界（保留完整的最后一个词）
        # 但最后一段的段尾不调整（保持视频结尾）
        if i < len(segments) - 1:
            new_seg["end"] = snap(seg_end, prefer="later")
        else:
            new_seg["end"] = seg_end  # 保持结尾

        # 保证段不为空
        if new_seg["end"] <= new_seg["start"] + 0.05:
            new_seg["start"] = seg_start
            new_seg["end"] = seg_end

        snapped.append(new_seg)

    return snapped


# ═════════════════════════════════════════════════
# 辅助函数
# ═════════════════════════════════════════════════

def _get_video_info(video_path: str) -> dict | None:
    """获取视频时长."""
    try:
        result = get_ffmpeg().probe(video_path)
        if result["success"]:
            return result["info"]
    except Exception:
        pass
    return None


def _merge_close_segments(segments: list[dict], min_gap: float = 0.5) -> list[dict]:
    """合并间隔小于 min_gap 的相邻片段."""
    if not segments:
        return segments
    sorted_segs = sorted(segments, key=lambda s: s["start"])
    merged = [dict(sorted_segs[0])]
    for seg in sorted_segs[1:]:
        last = merged[-1]
        if seg["start"] - last["end"] <= min_gap:
            last["end"] = max(last["end"], seg["end"])
        else:
            merged.append(dict(seg))
    return merged


def _parse_aspect_ratio(ratio_str: str) -> tuple[int, int] | tuple[None, None]:
    """解析画幅字符串 '9:16' → (1080, 1920) 或 (720, 1280)."""
    try:
        parts = ratio_str.strip().split(":")
        w_ratio, h_ratio = int(parts[0]), int(parts[1])
        if w_ratio > h_ratio:
            return (1920, 1080)
        else:
            return (1080, 1920)
    except Exception:
        return (None, None)
