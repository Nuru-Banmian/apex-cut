"""分析 Agent — Apex Legends 专用视频数据采集.

流程:
  Step 1: probe 视频元信息 → 计算抽帧参数
  Step 2: extract_frames 抽帧
  Step 3: 裁出右上角统计面板 → 发给视觉 LLM 读数

设计原则:
  - 百分比裁图，适配任意分辨率（2560×1440 / 1920×1080 / ...）
  - LLM 只看到统计面板裁图，不做空间推理
  - 只读伤害数，不读弹字
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
from apex_cut.tools.vision_tools import detect_combat_events
from apex_cut.sse import emit_progress, emit_progress_overwrite, emit_status
from apex_cut.cache import save_cache

# ★ 裁图参数 — 百分比，适配所有分辨率
# 右上角统计面板：右起 20%，顶起 10%
_STATS_LEFT_PCT  = 0.72   # 面板左边界（比赛信息在 72-96%，统计在更下方 8-14%）
_STATS_TOP_PCT   = 0.08   # 面板上边界（跳过顶部比赛信息"剩余小队"等）
_STATS_RIGHT_PCT = 0.96   # 面板右边界（留 4% 右边距）
_STATS_BOT_PCT   = 0.14   # 面板下边界


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
    print(f"[🔍 Apex 数据采集] {Path(video_path).name}")
    print(f"{'='*60}")

    # ── 视频元信息 ──
    emit_status("🔍 解析视频信息...")
    probe = _call_probe(video_path)
    duration = probe.get("duration", 0) if probe else 0
    print(f"  📹 {duration:.0f}s, {probe.get('width',0)}x{probe.get('height',0)}" if probe else "  ⚠️ probe 失败")

    # ── 抽帧参数 ──
    fi = state.get("frame_interval", 0) or 0
    interval = fi if fi > 0 else _auto_interval(duration)
    estimated = int(duration / interval) + 1 if duration > 0 else 0
    max_vis = state.get("max_vision_frames", 0) or 0
    frame_dir = str(Path(task_dir) / "frames")

    # ═════════════════════════════════════════════════════════
    # Step 1: 抽帧
    # ═════════════════════════════════════════════════════════
    emit_status(f"🔍 抽帧中 (间隔 {interval}s, ~{estimated} 张)...")

    tool = get_ffmpeg()
    try:
        r = tool.extract_frames(video_path, interval, frame_dir, estimated)
        frame_count = r.get("frame_count", 0) if r.get("success") else 0
        print(f"  🖼️  抽帧: {frame_count} 张")
    except Exception as e:
        frame_count = 0
        print(f"  🖼️  抽帧异常: {e}")

    # ═════════════════════════════════════════════════════════
    # Step 2: 视觉 LLM 读取 UI 数据
    # ═════════════════════════════════════════════════════════
    frame_files = sorted(Path(frame_dir).glob("frame_*.jpg"))
    vision_key = state.get("runtime_vision_key", "") or _get_runtime_vision_key()
    if not vision_key:
        vision_key = _fallback_vision_key(state)

    sample_count = len(frame_files) if max_vis == 0 else min(len(frame_files), max_vis)

    if frame_files and vision_key:
        print(f"\n  👁️  Apex 数据提取: {sample_count} 帧 (共 {len(frame_files)} 帧)")
        emit_status("👁️ 读取 UI 数据... 0%")

        try:
            frame_labels = _run_vision_analysis(frame_files, sample_count, interval, vision_key, state)
            frame_labels.sort(key=lambda f: f["frame"])
        except Exception as e:
            print(f"  ❌ 视觉分析异常: {e}")
            frame_labels = []
    else:
        if not vision_key:
            print(f"  ⏭️  无视觉 Key，跳过")
        frame_labels = []

    # ═════════════════════════════════════════════════════════
    # 统计 & 缓存
    # ═════════════════════════════════════════════════════════
    combat = sum(1 for f in frame_labels if f.get("_changes", {}).get("in_combat"))
    kills = sum(1 for f in frame_labels if f.get("_changes", {}).get("kill_occurred"))
    assists = sum(1 for f in frame_labels if f.get("_changes", {}).get("assist_occurred"))
    print(f"  📊 {len(frame_labels)} 帧 | 战斗={combat} 击杀={kills} 助攻={assists}")

    if frame_labels or probe:
        save_cache(video_path, {
            "probe_info": probe or {},
            "frame_labels": frame_labels,
        }, frame_interval=interval, max_vision_frames=max_vis)

    print(f"{'='*60}\n[🔍] 完成: {len(frame_labels)}帧标签\n{'='*60}")
    emit_status(f"✅ 数据采集完成 ({len(frame_labels)} 帧标签)")

    return {"frame_labels": frame_labels}


# ═══════════════════════════════════════════════════════════════
# 视觉分析核心 — 均匀采样 + 分批 LLM
# ═══════════════════════════════════════════════════════════════

def _crop_stats_panel(image_path: str) -> str | None:
    """裁出右上角统计面板 → base64.

    裁图区域（百分比，适配所有分辨率）：
      ┌─────────────────────────┬──┐
      │                         │🔢│ ← 右 20% × 上 10%
      │                         │  │   人头 助攻 [小队击杀] 伤害
      │       主画面             │  │
      │                         │  │
      └─────────────────────────┴──┘
    """
    try:
        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size
        left   = int(w * _STATS_LEFT_PCT)
        top    = int(h * _STATS_TOP_PCT)
        right  = int(w * _STATS_RIGHT_PCT)
        bottom = int(h * _STATS_BOT_PCT)
        crop = img.crop((left, top, right, bottom))
        buf = std_io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"  ⚠️ 裁图失败 {image_path}: {e}")
        return None


# ★ 裁图后提示词 — LLM 只看统计面板裁图，格式兼容新旧两种
STATS_SYSTEM = """你是 Apex Legends 个人统计面板数据读取器。
每张裁图是面板特写（3个横排数字: kills | assists | damage）。
* 非排位只有3个数字；排位有4个（多一个team_kills在assists和damage之间）
* team_kills在无第4个数字时填null

返回 JSON:
{"frames": [
  {"frame": 1, "player_stats": {"kills": null, "assists": null, "team_kills": null, "damage": null}},
  {"frame": 2, "player_stats": {"kills": 1, "assists": 2, "team_kills": null, "damage": 434}}
]}
规则：1.每图一个frame  2.看不清填null不猜  3.只返回JSON"""

STATS_HUMAN = "{frame_count} 张裁图，依次编号1-{frame_count}。每张读3-4个数字。只返回 JSON。"


def _run_vision_analysis(frame_files: list, sample_count: int, interval: float,
                         vision_key: str, state: dict,
                         chunk_size: int = 8) -> list[dict]:
    """裁出统计面板 → 多图并发 LLM 读数 → 战斗事件检测."""
    # 均匀采样
    step = max(1, len(frame_files) // sample_count)
    sampled = frame_files[::step][:sample_count]
    total = len(sampled)
    chunks = [sampled[i:i+chunk_size] for i in range(0, total, chunk_size)]
    total_chunks = len(chunks)

    try:
        llm = create_multimodal_llm(
            runtime_api_key=vision_key,
            runtime_provider=state.get("runtime_vision_provider", "") or _get_runtime_vision_provider(),
            runtime_model=state.get("runtime_vision_model", "") or _get_runtime_vision_model(),
        )
    except Exception as e:
        print(f"  ❌ LLM 初始化失败: {e}")
        return []

    all_labels = []

    for chunk_idx, chunk in enumerate(chunks):
        chunk_num = chunk_idx + 1
        first_fn = int(chunk[0].stem.split("_")[-1])
        last_fn = int(chunk[-1].stem.split("_")[-1])

        # ── 裁图 + 编码 ──
        human_text = STATS_HUMAN.format(
            frame_count=len(chunk),
            chunk_start=first_fn,
            chunk_end=last_fn,
        )
        content_parts = [{"type": "text", "text": human_text}]
        chunk_kb = 0

        for i, fpath in enumerate(chunk):
            b64 = _crop_stats_panel(str(fpath))
            if b64 is None:
                # 裁图失败 → 用原图（fallback）
                b64 = _encode_image(str(fpath), max_px=400)
            chunk_kb += len(b64)
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
            fn = int(fpath.stem.split("_")[-1])

        pct = round(chunk_num / total_chunks * 100)
        emit_status(f"👁️ 读取伤害数据... {pct}%")
        msg = f"  📤 批次 {chunk_num}/{total_chunks} ({first_fn}-{last_fn} 帧, {chunk_kb/1024:.0f}KB)..."
        print(f"\r{msg}", end="", flush=True)
        emit_progress_overwrite(msg)

        filled = set()
        raw_frames = []

        # ── LLM 调用 ──
        try:
            resp = llm.invoke([HumanMessage(content=[
                {"type": "text", "text": STATS_SYSTEM},
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

            # ★ 空响应重试一次
            if not raw_frames:
                print(f"\r  ⚠️ 批次 {chunk_num} 空响应，重试...")
                try:
                    resp2 = llm.invoke([HumanMessage(content=[
                        {"type": "text", "text": "上次返回为空。请严格返回 JSON：{\"frames\": [...]}"},
                        *content_parts,
                    ])])
                    resp_text2 = resp2.content.strip() if hasattr(resp2, 'content') else str(resp2)
                    result2 = json.loads(_extract_json(resp_text2))
                    raw_frames = result2.get("frames", [])
                    if not raw_frames:
                        if isinstance(result2, list): raw_frames = result2
                        elif isinstance(result2, dict) and "frame" in result2: raw_frames = [result2]
                except Exception:
                    raw_frames = []

            # 构建帧号→文件映射（LLM可能返回序号1-N或实际帧号，都兼容）
            fn_map = {i+1: int(f.stem.split('_')[-1]) for i, f in enumerate(chunk)}

            for item in raw_frames:
                item_fn = item.get("frame", 0)
                # 尝试两种映射：1-based序号 或 实际帧号
                actual_fn = fn_map.get(item_fn)  # 序号映射
                if actual_fn is None:
                    actual_fn = item_fn if any(int(f.stem.split('_')[-1]) == item_fn for f in chunk) else None
                if actual_fn is None:
                    continue

                ps = item.get("player_stats") or {}
                all_labels.append({
                    "frame": actual_fn,
                    "time_seconds": round((actual_fn - 1) * interval, 1),
                    "player_stats": {
                        "kills": ps.get("kills") if ps.get("kills") is not None else item.get("kills"),
                        "assists": ps.get("assists") if ps.get("assists") is not None else item.get("assists"),
                        "team_kills": ps.get("team_kills") if ps.get("team_kills") is not None else item.get("team_kills"),
                        "damage": ps.get("damage") if ps.get("damage") is not None else item.get("damage"),
                    },
                })
                filled.add(actual_fn)

        except json.JSONDecodeError:
            print(f"\r  ⚠️ 批次 {chunk_num} JSON 异常，重试...")
            try:
                retry_content = [{"type": "text", "text": "上轮格式有误。严格只返回 JSON：{\"frames\": [...]}"}]
                retry_content.extend(content_parts[1:])
                resp2 = llm.invoke([HumanMessage(content=retry_content)])
                resp_text2 = resp2.content.strip() if hasattr(resp2, 'content') else str(resp2)
                result2 = json.loads(_extract_json(resp_text2))
                raw_frames2 = result2.get("frames", [])
                if not raw_frames2:
                    if isinstance(result2, list): raw_frames2 = result2
                    elif isinstance(result2, dict) and "frame" in result2: raw_frames2 = [result2]
                fn_map = {i+1: int(f.stem.split('_')[-1]) for i, f in enumerate(chunk)}
                for item in raw_frames2:
                    item_fn = item.get("frame", 0)
                    actual_fn = fn_map.get(item_fn)
                    if actual_fn is None:
                        actual_fn = item_fn if any(int(f.stem.split('_')[-1]) == item_fn for f in chunk) else None
                    if actual_fn is None:
                        continue
                    ps = item.get("player_stats") or {}
                    all_labels.append({
                        "frame": actual_fn, "time_seconds": round((actual_fn - 1) * interval, 1),
                        "player_stats": {
                            "kills": ps.get("kills") if ps.get("kills") is not None else item.get("kills"),
                            "assists": ps.get("assists") if ps.get("assists") is not None else item.get("assists"),
                            "team_kills": ps.get("team_kills") if ps.get("team_kills") is not None else item.get("team_kills"),
                            "damage": ps.get("damage") if ps.get("damage") is not None else item.get("damage"),
                        },
                    })
                    filled.add(actual_fn)
                raw_frames = raw_frames2
                print(f"\r  ✅ 批次 {chunk_num} 重试成功 ({len(raw_frames2)} 帧)")
            except Exception:
                print(f"\r  ❌ 批次 {chunk_num} 重试也失败")

        except Exception as e:
            print(f"\r  ❌ 批次 {chunk_num} 失败: {e}")

        # ★ 补全 LLM 漏掉的帧
        missed = 0
        for fpath in chunk:
            fn = int(fpath.stem.split("_")[-1])
            if fn not in filled:
                all_labels.append({
                    "frame": fn,
                    "time_seconds": round((fn - 1) * interval, 1),
                    "player_stats": {"kills": None, "assists": None, "team_kills": None, "damage": None},
                })
                missed += 1

        tag = f"{len(raw_frames)}帧"
        if missed: tag += f", +{missed}补空"
        print(f"\r  ✅ 批次 {chunk_num}/{total_chunks} ({tag})" + " " * 20)
        emit_progress_overwrite(f"  ✅ 批次 {chunk_num}/{total_chunks} ({tag})")

    # ★ 比较相邻帧数字变化 → 检测战斗事件
    all_labels.sort(key=lambda f: f["frame"])
    try:
        all_labels = detect_combat_events(all_labels)
    except Exception as e:
        print(f"  ⚠️ detect_combat_events 异常: {e}")

    return all_labels


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _auto_interval(duration: float) -> float:
    """默认抽帧间隔 — 固定 1s（前端高级设置可覆盖）."""
    return 1.0


def _fallback_vision_key(state: dict) -> str:
    vp = state.get("runtime_vision_provider", "") or settings.vision_provider
    if vp == "zhipu": return settings.zhipu_api_key
    if vp == "qwen": return settings.qwen_api_key
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
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 1: lines = lines[1:]
        if lines and lines[-1].strip() == "```": lines = lines[:-1]
        text = "\n".join(lines)
    return text
