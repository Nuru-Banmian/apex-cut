"""分析 Agent — 多 ROI 区域视觉分析 + LLM 战斗判断.

v2 流程:
  Step 1: probe 视频元信息 → 计算抽帧参数
  Step 2: extract_frames 抽帧
  Step 3: 读取 ROI 配置（用户框选 or 默认统计面板）
  Step 4: 按 ROI 逐区域裁图 → 发给视觉 LLM 综合判断战斗
  Step 5: 输出 {has_combat, event, confidence} 直接用于 Editor

与 v1 的核心区别:
  - v1: 裁统计面板 → LLM 读数 → 代码 diff 数字 → 判定战斗
  - v2: 裁多个 ROI 区域 → LLM 综合所有信号 → 直接输出战斗事件
"""

from __future__ import annotations

import base64
import io as std_io
import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from apex_cut.state import VideoEditState
from apex_cut.config import (
    _get_runtime_vision_key, OUTPUT_DIR, settings,
    create_multimodal_llm, _get_runtime_vision_provider, _get_runtime_vision_model,
)
from apex_cut.tools.video_tools import get_ffmpeg
from apex_cut.tools.vision_tools import parse_combat_result
from apex_cut.sse import emit_progress, emit_progress_overwrite, emit_status
from apex_cut.cache import save_cache

#  默认裁图参数（无 ROI 配置时的 fallback）
# 右上角统计面板：人头 | 助攻 | [小队击杀] | 伤害
_STATS_LEFT_PCT  = 0.72
_STATS_TOP_PCT   = 0.08
_STATS_RIGHT_PCT = 0.96
_STATS_BOT_PCT   = 0.14


# ═══════════════════════════════════════════════════════════════
# 主分析节点
# ═══════════════════════════════════════════════════════════════

def analyzer_node(state: VideoEditState) -> dict:
    """Apex 数据采集 — 抽帧+场景并行 → 视觉LLM分析."""
    video_path = state.get("video_path", "")
    requirement = state.get("user_requirement", "")
    task_dir = state.get("output_dir", str(OUTPUT_DIR))

    if not video_path:
        return {"error": "未提供视频路径"}

    print(f"\n{'='*60}")
    print(f"[ Apex 数据采集] {Path(video_path).name}")
    print(f"{'='*60}")

    # ── 视频元信息 ──
    emit_status(" 解析视频信息...")
    probe = _call_probe(video_path)
    duration = probe.get("duration", 0) if probe else 0
    print(f"   {duration:.0f}s, {probe.get('width',0)}x{probe.get('height',0)}" if probe else "  ️ probe 失败")

    # ── 抽帧参数 ──
    fi = state.get("frame_interval", 0) or 0
    interval = fi if fi > 0 else _auto_interval(duration)
    estimated = int(duration / interval) + 1 if duration > 0 else 0
    max_vis = state.get("max_vision_frames", 0) or 0
    frame_dir = str(Path(task_dir) / "frames")

    # ═════════════════════════════════════════════════════════
    # Step 1: 抽帧
    # ═════════════════════════════════════════════════════════
    emit_status(f" 抽帧中 (间隔 {interval}s, ~{estimated} 张)...")

    tool = get_ffmpeg()
    try:
        r = tool.extract_frames(video_path, interval, frame_dir, estimated)
        frame_count = r.get("frame_count", 0) if r.get("success") else 0
        print(f"  ️  抽帧: {frame_count} 张")
    except Exception as e:
        frame_count = 0
        print(f"  ️  抽帧异常: {e}")

    # ═════════════════════════════════════════════════════════
    # Step 2: 视觉 LLM 读取 UI 数据
    # ═════════════════════════════════════════════════════════
    frame_files = sorted(Path(frame_dir).glob("frame_*.jpg"))
    vision_key = state.get("runtime_vision_key", "") or _get_runtime_vision_key()
    if not vision_key:
        vision_key = _fallback_vision_key(state)

    sample_count = len(frame_files) if max_vis == 0 else min(len(frame_files), max_vis)
    roi_config = state.get("roi_config") or []

    if frame_files and vision_key:
        mode_tag = f"{len(roi_config)} ROI" if roi_config else "默认面板"
        print(f"\n  ️  Apex 数据提取: {sample_count} 帧 ({mode_tag})")
        emit_status("️ 读取 UI 数据... 0%")

        try:
            frame_labels = _run_vision_analysis(
                frame_files, sample_count, interval, vision_key, state, roi_config,
            )
            frame_labels.sort(key=lambda f: f["frame"])
        except Exception as e:
            print(f"   视觉分析异常: {e}")
            frame_labels = []
    else:
        if not vision_key:
            print(f"  ️  无视觉 Key，跳过")
        frame_labels = []

    # ═════════════════════════════════════════════════════════
    # 统计 & 缓存
    # ═════════════════════════════════════════════════════════
    combat = sum(1 for f in frame_labels if f.get("has_combat"))
    kills = sum(1 for f in frame_labels if f.get("event") == "kill")
    assists = sum(1 for f in frame_labels if f.get("event") == "assist")
    print(f"   {len(frame_labels)} 帧 | 战斗={combat} 击杀={kills} 助攻={assists}")

    if frame_labels or probe:
        save_cache(video_path, {
            "probe_info": probe or {},
            "frame_labels": frame_labels,
        }, frame_interval=interval, max_vision_frames=max_vis,
           roi_hash=state.get("roi_hash", ""))

    print(f"{'='*60}\n[] 完成: {len(frame_labels)}帧标签\n{'='*60}")
    emit_status(f" 数据采集完成 ({len(frame_labels)} 帧标签)")

    return {"frame_labels": frame_labels}


# ═══════════════════════════════════════════════════════════════
# 视觉分析核心 — 默认裁图 or 多 ROI 裁图 → LLM 战斗判断
# ═══════════════════════════════════════════════════════════════

def _crop_region(image_path: str, rect: dict) -> str | None:
    """裁出指定百分比区域 → base64.

    rect: {x, y, w, h}  百分比坐标 (0.0~1.0)
    """
    try:
        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size
        left   = int(w * rect["x"])
        top    = int(h * rect["y"])
        right  = int(w * (rect["x"] + rect["w"]))
        bottom = int(h * (rect["y"] + rect["h"]))
        # 保证最小 1px
        if right <= left or bottom <= top:
            return None
        crop = img.crop((left, top, right, bottom))
        buf = std_io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"  ️ 裁图失败 {image_path}: {e}")
        return None


# ── 默认面板裁图（兼容旧坐标常量）──

def _crop_default_panel(image_path: str) -> str | None:
    """裁出右上角统计面板（硬编码坐标 fallback）."""
    return _crop_region(image_path, {
        "x": _STATS_LEFT_PCT,
        "y": _STATS_TOP_PCT,
        "w": _STATS_RIGHT_PCT - _STATS_LEFT_PCT,
        "h": _STATS_BOT_PCT - _STATS_TOP_PCT,
    })


# ── Prompt：默认模式（只有统计面板，LLM 从数字判断战斗）──

DEFAULT_COMBAT_SYSTEM = """你是 FPS 游戏战斗信号分析器。
每张裁图是游戏统计面板特写，包含击杀数、助攻数、伤害数等 UI 数据。

## ⚠️ 关键概念：累计 vs 帧间变化

面板上所有数字都是**累计值**（本局从开局到现在的总和），不是"这一秒发生的事"：
- 击杀数=5  → 本局累计杀了 5 个人，不表示这一帧杀了人
- 伤害=1234  → 本局累计打了 1234 伤害，不表示这一帧在打伤害
- 数字大 ≠ 正在打架，只说明**之前打过架**

## 判断方法：帧间对比

你收到的裁图按帧号 1,2,3... 顺序排列，帧之间相隔约 2 秒。
**对比相邻帧的数字变化**才是检测战斗的唯一可靠方法：

- 帧1 → 帧2：击杀数 0→1 = 发生了击杀 → kill
- 帧1 → 帧2：伤害 100→250 = 此间隔打出 150 伤害 → combat
- 帧1 → 帧2：助攻 0→0、击杀 0→0、伤害不变 = 无新事件 → none
- 帧2 → 帧3：数字与帧2完全相同 = 无战斗 → none

## 事件类型
- **combat** — 相邻帧比较，伤害数字明显增加（差值 > 30）
- **none** — 伤害数字无变化、或看不清、或无法判断

不用判断击杀/助攻，只判断是否在打架。

## 置信度
- **high** — 数字清晰，变化明确
- **medium** — 数字可见但部分模糊，变化可推断
- **low** — 数字模糊，不确定是否变化（设 event=none）

## numbers 字段（只填数字，不写字）
- `damage` 是 `[prev, curr]` 数组
- prev = 本批上一帧的伤害值，curr = 当前帧的伤害值
- 本批第一帧：prev 填 curr 相同值（无前帧可比）
- 数字看不清填 null，禁止猜
- kills / assists 也填但不用于判断（固定填 [null, null] 即可）
- **绝对禁止在 numbers 里写任何文字、描述、推理**

## 输出（严格 JSON）
{"frames": [
  {"frame": 1, "event": "none", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [0,0]}},
  {"frame": 2, "event": "combat", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [0,234]}},
  {"frame": 3, "event": "none", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [234,234]}}
]}

只返回 JSON。"""

DEFAULT_COMBAT_HUMAN = "{frame_count} 张统计面板裁图，按帧号1-{frame_count}顺序排列（间隔约2秒）。注意数字是累计值，请对比相邻帧的变化来判断。只返回 JSON。"


# ── Prompt：ROI 模式（多区域裁图，LLM 综合判断）──

ROI_COMBAT_SYSTEM = """你是 FPS 游戏战斗信号分析器。

## 工作方式
每帧有多个裁图区域，你只需要看伤害数字的变化。

## ⚠️ 累计值规则（最重要）

伤害数字是**累计值**（从开局到现在的总和）：
- 伤害=1234 → 整局累计，不表示这一帧在打伤害

**唯一判定：对比相邻帧的伤害数字变化**

帧 N → 帧 N+1：
- 伤害增加 > 30 → combat（在打架）
- 伤害不变或看不清 → none

不用判断击杀/助攻/文字提示。只看伤害数字。

## 置信度
- **high** — 伤害数字清晰，相邻帧变化明确
- **medium** — 伤害数字可见但模糊，变化可推断
- **low** — 数字模糊，不确定是否变化（设 event=none）

## 规则
1. 伤害数字增加 > 30 = combat；否则 = none。就这么简单。
2. 视觉特效、画面内容、文字提示全部忽略，不参与判断。
3. 没看清就报 none / low，宁可漏抓不误抓。

## numbers 字段（只填数字，不写字）
- `damage` 是 `[prev, curr]` 数组
- 多个 ROI 区域的伤害数字取 total_damage 区域的读数
- prev = 本批上一帧的值，curr = 当前帧的值
- 本批第一帧：prev 填 curr 相同值（无前帧可比）
- 数字看不清填 null，禁止猜
- kills / assists 固定填 [null, null]
- **绝对禁止在 numbers 里写任何文字、描述、推理、kill_feed 状态、区域名**

## 输出（严格 JSON）
{"frames": [
  {"frame": 1, "event": "none", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [0,0]}},
  {"frame": 2, "event": "combat", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [0,234]}},
  {"frame": 3, "event": "none", "confidence": "high", "numbers": {"kills": [null,null], "assists": [null,null], "damage": [234,234]}}
]}

只返回 JSON。"""

ROI_COMBAT_HUMAN = "{frame_count} 帧裁图，每帧 {roi_count} 个区域，按帧号1-{frame_count}顺序排列（间隔约2秒）。每个区域只读数字或文字。对比相邻帧的变化。只返回 JSON。"


# ── 主分析函数 ──

def _run_vision_analysis(frame_files: list, sample_count: int, interval: float,
                         vision_key: str, state: dict,
                         roi_config: list[dict] | None = None,
                         chunk_size: int = 8) -> list[dict]:
    """裁图 → LLM 战斗判断 → 输出 {has_combat, event, confidence}.

    两种模式:
      - ROI 模式: 用户配置了 roi_config → 按区域裁图 → LLM 综合判断
      - 默认模式: 无 roi_config → 裁右上统计面板 → LLM 从数字判断
    """
    # 均匀采样
    step = max(1, len(frame_files) // sample_count)
    sampled = frame_files[::step][:sample_count]
    total = len(sampled)

    # ROI 模式下减少每批帧数（每帧多张图）
    if roi_config:
        chunk_size = max(3, chunk_size // 2)

    # ── 重叠批：每批最后一帧 = 下一批第一帧，确保跨批边界帧间对比不丢失 ──
    chunks = []
    i = 0
    while i < total:
        end = min(i + chunk_size, total)
        chunks.append(sampled[i:end])
        if end >= total:
            break
        i = end - 1  # 重叠 1 帧
    total_chunks = len(chunks)

    try:
        llm = create_multimodal_llm(
            runtime_api_key=vision_key,
            runtime_provider=state.get("runtime_vision_provider", "") or _get_runtime_vision_provider(),
            runtime_model=state.get("runtime_vision_model", "") or _get_runtime_vision_model(),
        )
    except Exception as e:
        print(f"   LLM 初始化失败: {e}")
        return []

    if roi_config:
        return _analyze_chunks_roi(chunks, roi_config, interval, llm, total_chunks)
    else:
        return _analyze_chunks_default(chunks, interval, llm, total_chunks)


# ═══════════════════════════════════════════════════════════════
# 默认模式 — 统计面板裁图 + LLM 战斗判断
# ═══════════════════════════════════════════════════════════════

def _analyze_chunks_default(chunks: list, interval: float, llm,
                            total_chunks: int) -> list[dict]:
    """每帧裁出右上统计面板 → 批量发给 LLM 判断战斗."""
    all_labels = []

    for chunk_idx, chunk in enumerate(chunks):
        chunk_num = chunk_idx + 1
        first_fn = int(chunk[0].stem.split("_")[-1])
        last_fn = int(chunk[-1].stem.split("_")[-1])

        human_text = DEFAULT_COMBAT_HUMAN.format(frame_count=len(chunk))
        content_parts = [{"type": "text", "text": human_text}]
        chunk_kb = 0

        for fpath in chunk:
            b64 = _crop_default_panel(str(fpath))
            if b64 is None:
                b64 = _encode_image(str(fpath), max_px=400)
            chunk_kb += len(b64)
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        pct = round(chunk_num / total_chunks * 100)
        emit_status(f"️ 战斗检测... {pct}%")
        msg = f"   批次 {chunk_num}/{total_chunks} ({first_fn}-{last_fn} 帧, {chunk_kb/1024:.0f}KB)..."
        print(f"\r{msg}", end="", flush=True)
        emit_progress_overwrite(msg)

        raw_frames = _call_llm_with_retry(llm, DEFAULT_COMBAT_SYSTEM, content_parts, chunk_num)
        filled = set()
        fn_map = {i+1: int(f.stem.split("_")[-1]) for i, f in enumerate(chunk)}

        for item in raw_frames:
            actual_fn = _resolve_frame_num(item, fn_map, chunk)
            if actual_fn is None:
                continue
            all_labels.append(parse_combat_result(item, actual_fn, interval))
            filled.add(actual_fn)

        # 补全漏帧
        _fill_missed(all_labels, chunk, filled, interval)

        tag = f"{len(raw_frames)}帧"
        missed = len(chunk) - len(filled)
        if missed: tag += f", +{missed}补空"
        print(f"\r   批次 {chunk_num}/{total_chunks} ({tag})" + " " * 20)
        emit_progress_overwrite(f"   批次 {chunk_num}/{total_chunks} ({tag})")

    all_labels = _dedup_labels(all_labels)
    all_labels.sort(key=lambda f: f["frame"])
    return all_labels


# ═══════════════════════════════════════════════════════════════
# ROI 模式 — 多区域裁图 + LLM 综合判断
# ═══════════════════════════════════════════════════════════════

def _analyze_chunks_roi(chunks: list, roi_config: list[dict], interval: float,
                        llm, total_chunks: int) -> list[dict]:
    """每帧按 ROI 配置裁多个区域 → 批量发给 LLM 综合判断战斗.

    每帧的裁图按 ROI 顺序排列，LLM 根据各区域信号综合判断。
    """
    from apex_cut.roi_types import ROI_TYPE_MAP

    all_labels = []
    roi_count = len(roi_config)

    for chunk_idx, chunk in enumerate(chunks):
        chunk_num = chunk_idx + 1
        first_fn = int(chunk[0].stem.split("_")[-1])
        last_fn = int(chunk[-1].stem.split("_")[-1])

        human_text = ROI_COMBAT_HUMAN.format(
            frame_count=len(chunk), roi_count=roi_count,
        )
        content_parts = [{"type": "text", "text": human_text}]
        chunk_kb = 0

        for frame_idx, fpath in enumerate(chunk):
            # 帧标签
            fn = int(fpath.stem.split("_")[-1])
            content_parts.append({
                "type": "text",
                "text": f"── 帧 {frame_idx+1} (帧号{fn}) ──",
            })

            for roi_idx, roi in enumerate(roi_config):
                rect = roi.get("rect", {})
                if not rect:
                    continue
                b64 = _crop_region(str(fpath), rect)
                if b64 is None:
                    continue
                chunk_kb += len(b64)

                # 获取该 ROI 的指令
                type_id = roi.get("type_id", "custom")
                roi_type = ROI_TYPE_MAP.get(type_id)
                instruction = roi.get("custom_instruction", "").strip()
                if not instruction and roi_type:
                    instruction = roi_type.instruction
                label = roi.get("label", "") or roi_type.name if roi_type else f"ROI{roi_idx+1}"

                content_parts.append({
                    "type": "text",
                    "text": f"[{label}] {instruction}",
                })
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })

        pct = round(chunk_num / total_chunks * 100)
        emit_status(f"️ 战斗检测 (ROI)... {pct}%")
        roi_tag = f"{roi_count}区×{len(chunk)}帧"
        msg = f"   批次 {chunk_num}/{total_chunks} ({roi_tag}, {chunk_kb/1024:.0f}KB)..."
        print(f"\r{msg}", end="", flush=True)
        emit_progress_overwrite(msg)

        raw_frames = _call_llm_with_retry(llm, ROI_COMBAT_SYSTEM, content_parts, chunk_num)
        filled = set()
        fn_map = {i+1: int(f.stem.split("_")[-1]) for i, f in enumerate(chunk)}

        for item in raw_frames:
            actual_fn = _resolve_frame_num(item, fn_map, chunk)
            if actual_fn is None:
                continue
            all_labels.append(parse_combat_result(item, actual_fn, interval))
            filled.add(actual_fn)

        _fill_missed(all_labels, chunk, filled, interval)

        tag = f"{len(raw_frames)}帧"
        missed = len(chunk) - len(filled)
        if missed: tag += f", +{missed}补空"
        print(f"\r   批次 {chunk_num}/{total_chunks} ({tag})" + " " * 20)
        emit_progress_overwrite(f"   批次 {chunk_num}/{total_chunks} ({tag})")

    all_labels = _dedup_labels(all_labels)
    all_labels.sort(key=lambda f: f["frame"])
    return all_labels


# ═══════════════════════════════════════════════════════════════
# LLM 调用 + 重试
# ═══════════════════════════════════════════════════════════════

def _call_llm_with_retry(llm, system_prompt: str, content_parts: list,
                         chunk_num: int) -> list[dict]:
    """调用视觉 LLM → 解析 JSON → 失败时重试一次."""
    try:
        resp = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": system_prompt},
            *content_parts,
        ])])
        resp_text = resp.content.strip() if hasattr(resp, 'content') else str(resp)
        json_str = _extract_json(resp_text)
        result = json.loads(json_str)
        raw_frames = result.get("frames", [])
        if not raw_frames:
            if isinstance(result, list):
                raw_frames = result
            elif isinstance(result, dict) and "frame" in result:
                raw_frames = [result]

        if not raw_frames:
            raise json.JSONDecodeError("empty frames array", resp_text[:200], 0)

        return raw_frames

    except json.JSONDecodeError:
        print(f"\r  ️ 批次 {chunk_num} JSON 异常，重试...")
    except Exception as e:
        print(f"\r   批次 {chunk_num} 失败: {e}")

    # ── 重试 ──
    try:
        retry_content = [{"type": "text", "text": "上轮格式有误，请严格只返回 JSON：{\"frames\": [...]}"}]
        retry_content.extend(content_parts)
        resp2 = llm.invoke([HumanMessage(content=retry_content)])
        resp_text2 = resp2.content.strip() if hasattr(resp2, 'content') else str(resp2)
        result2 = json.loads(_extract_json(resp_text2))
        raw_frames2 = result2.get("frames", [])
        if not raw_frames2:
            if isinstance(result2, list): raw_frames2 = result2
            elif isinstance(result2, dict) and "frame" in result2: raw_frames2 = [result2]
        if raw_frames2:
            print(f"\r   批次 {chunk_num} 重试成功 ({len(raw_frames2)} 帧)")
            return raw_frames2
    except Exception:
        pass

    print(f"\r   批次 {chunk_num} 重试也失败")
    return []


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _resolve_frame_num(item: dict, fn_map: dict, chunk: list) -> int | None:
    """解析 LLM 返回的帧号 → 实际帧号."""
    item_fn = item.get("frame", 0)
    # 1-based 序号映射
    actual = fn_map.get(item_fn)
    if actual is not None:
        return actual
    # 直接匹配实际帧号
    if any(int(f.stem.split("_")[-1]) == item_fn for f in chunk):
        return item_fn
    return None


def _dedup_labels(labels: list[dict]) -> list[dict]:
    """去重重叠批产生的重复帧，优先保留事件更好的标签.

    事件优先级: kill > assist > combat > none
    """
    evt_rank = {"combat": 1, "none": 0}
    best: dict[int, dict] = {}
    for item in labels:
        fn = item["frame"]
        if fn not in best or evt_rank.get(item.get("event", "none"), 0) > evt_rank.get(best[fn].get("event", "none"), 0):
            best[fn] = item
    return list(best.values())


def _fill_missed(all_labels: list, chunk: list, filled: set, interval: float):
    """补全 LLM 漏掉的帧（标记为 none/low）."""
    for fpath in chunk:
        fn = int(fpath.stem.split("_")[-1])
        if fn not in filled:
            all_labels.append({
                "frame": fn,
                "time_seconds": round((fn - 1) * interval, 1),
                "has_combat": False,
                "event": "none",
                "confidence": "low",
                "note": "LLM 未返回，补空",
                "numbers": {"kills": [None, None], "assists": [None, None], "damage": [None, None]},
            })


def _auto_interval(duration: float) -> float:
    """默认抽帧间隔 — 固定 2s（前端高级设置可覆盖）."""
    return 2.0


def _fallback_vision_key(state: dict) -> str:
    """根据 provider 回退到 settings 中对应的 API Key.

    对齐 create_multimodal_llm 支持的视觉提供商:
      zhipu / qwen / anthropic / openai
    其余 provider（doubao / lingyi 等）依赖前端传入的运行时 Key，
    这里无 settings 字段可回退，返回空字符串。
    """
    vp = state.get("runtime_vision_provider", "") or settings.vision_provider
    if vp == "zhipu": return settings.zhipu_api_key
    if vp == "qwen": return settings.qwen_api_key
    if vp == "anthropic": return settings.anthropic_api_key
    # openai + 所有未在 Settings 中定义 API key 的 provider
    return settings.openai_api_key


def _call_probe(video_path: str) -> dict | None:
    try:
        r = get_ffmpeg().probe(video_path)
        return r.get("info", {}) if r.get("success") else None
    except Exception:
        return None


def _encode_image(image_path: str, max_px: int = 0) -> str:
    max_size = max_px or settings.vision_max_px
    try:
        from PIL import Image
        import io
        img = Image.open(image_path)
        w, h = img.size
        longest = max(w, h)
        if longest > max_size:
            ratio = max_size / longest
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


def _extract_json(text: str) -> str:
    """从 LLM 返回文本中提取纯 JSON（处理 markdown fence / 混杂文本）."""
    if not text or not text.strip():
        raise json.JSONDecodeError("empty response", "", 0)

    # 1. markdown fence ```json ... ```
    fence_start = text.find("```")
    if fence_start != -1:
        after = text[fence_start + 3:]
        nl = after.find("\n")
        json_part = after[nl + 1:] if nl != -1 else after
        fence_end = json_part.find("```")
        if fence_end != -1:
            return json_part[:fence_end].strip()

    # 2. 括号匹配提取
    brace = text.find("{")
    if brace == -1:
        raise json.JSONDecodeError("no JSON object found", text[:200], 0)

    depth = 0
    end = -1
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise json.JSONDecodeError("unclosed JSON object", text[brace:brace+200], 0)

    return text[brace:end].strip()
