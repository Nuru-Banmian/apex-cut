"""多模态视觉分析工具.

工具列表:
  - describe_frames: 逐帧画面描述（通用用途）
  - classify_frames_apex: (legacy v1) Apex UI 读数 + 代码事件检测 — v2 不再使用
  - parse_combat_result: (v2) 将 LLM JSON 转换为标准 frame_label

v2 战斗检测主线在 analyzer.py 的 _run_vision_analysis 中.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from langchain_core.tools import tool

from apex_cut.config import (
    create_multimodal_llm,
    _get_runtime_vision_key,
    _get_runtime_vision_provider,
    _get_runtime_vision_model,
    settings,
)
from apex_cut.sse import emit_progress, emit_progress_overwrite, emit_status


def _encode_image(image_path: str, max_px: int = 0) -> str:
    """将图片缩放后编码为 base64 data URL."""
    max_size = max_px or settings.vision_max_px
    try:
        from PIL import Image
        import io
        img = Image.open(image_path)
        w, h = img.size
        longest = max(w, h)
        if longest > max_size:
            ratio = max_size / longest
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


# ═══════════════════════════════════════════════════════════════
# Apex 专用：画面数据提取 Prompt
# ═══════════════════════════════════════════════════════════════

VISION_APEX_SYSTEM = """你是 Apex Legends 游戏画面数据提取器。
唯一任务：**读取 UI 上的数字**，不做画面描述。

## 最右上角 — 玩家数据面板
位置：画面最右上角的一小块区域
**横向排列**，从左到右依次是：

┌─────────────────────────────┐
│ 5    2    7    1234  │
│ 人头   助攻   小队击杀  伤害  │
└─────────────────────────────┘

- **人头**(kills)：你的本局累计击杀数
- **助攻**(assists)：你的本局累计助攻数
- **小队击杀**(team_kills)：️ 注意！这个数据**只在排位赛中存在**。非排位（匹配/娱乐模式）画面中只有三个数字（人头、助攻、伤害），没有这个字段。如果只看到三个数字，team_kills **填 null 不要强读**。
- **伤害**(damage)：你的本局累计伤害数

**非排位画面（三个数字，从左到右）：**
┌──────────────────────┐
│ 5    2    1234  │
└──────────────────────┘

**排位画面（四个数字，从左到右）：**
┌─────────────────────────────┐
│ 5    2    7    1234  │
└─────────────────────────────┘

数字变化含义：
- 人头增加 → 你完成了一次击杀
- 助攻增加 → 队友击杀了，你蹭到助攻
- 小队击杀增加但人头没增加 → 队友单独击杀，你不在场（仅排位）
- 伤害增加 → 你在对敌人造成伤害（正在交火）

读出：
{
  "player_stats": {
    "kills": 数字或null,
    "assists": 数字或null,
    "team_kills": 数字或null,
    "damage": 数字或null
  }
}

# 输出格式

返回一个 JSON 对象，每帧作为 frames 数组的一个元素：

{"frames": [
  {
    "frame": 1,
    "player_stats": {"kills": null, "assists": null, "team_kills": null, "damage": null}
  },
  {
    "frame": 2,
    "player_stats": {"kills": 3, "assists": 1, "team_kills": 4, "damage": 567}
  }
]}

# 规则
1. 有几张图就输出几个 frame 对象，放 frames 数组里
2. 数字看不清填 null，不要猜
3. 右上角面板从左到右读取数字
4. 只返回 JSON，不要任何额外文字"""


VISION_APEX_HUMAN = """以下是 {frame_count} 帧 Apex Legends 画面（第 {chunk_start}-{chunk_end} 帧）。

逐帧读取右上角面板数据：人头、助攻、小队击杀、伤害数字。

只返回 JSON。"""


# ═══════════════════════════════════════════════════════════════
# v3 — LLM 全权判断 combat/none，代码仅做格式校验 + note 生成
# ═══════════════════════════════════════════════════════════════

# ── 合法值白名单 ──
_VALID_EVENTS = {"combat", "none"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


def parse_combat_result(llm_json: dict, frame_num: int, interval: float) -> dict:
    """解析 LLM 返回的 JSON → 标准 frame_label.

    LLM 全权判断 event（combat / none），代码只做格式校验和 note 生成，
    不再覆盖 LLM 的判断结果。

    LLM 输出格式:
      {"frame": 2, "event": "combat", "confidence": "high",
       "numbers": {"kills": [null,null], "assists": [null,null], "damage": [0,234]}}
    """
    # ── numbers 解析 ──
    numbers = llm_json.get("numbers", {})
    if not isinstance(numbers, dict):
        numbers = {}

    def _safe_pair(key: str) -> list:
        """提取 [prev, curr]，保证是两个元素的 int/None 列表."""
        pair = numbers.get(key)
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            return [None, None]
        result = []
        for v in pair[:2]:
            if isinstance(v, (int, float)) and v >= 0:
                result.append(int(v))
            else:
                result.append(None)
        return result

    kills = _safe_pair("kills")
    assists = _safe_pair("assists")
    damage = _safe_pair("damage")

    # ── event 仅做白名单校验，信任 LLM 判断 ──
    event = llm_json.get("event", "none")
    if not isinstance(event, str) or event not in _VALID_EVENTS:
        event = "none"

    # ── confidence 校验 ──
    confidence = llm_json.get("confidence", "low")
    if not isinstance(confidence, str) or confidence not in _VALID_CONFIDENCE:
        confidence = "low"

    # ── has_combat 自动派生 ──
    has_combat = event != "none"

    # ── 代码生成 note ──
    note = _build_note(kills, assists, damage)

    return {
        "frame": frame_num,
        "time_seconds": round((frame_num - 1) * interval, 1),
        "has_combat": has_combat,
        "event": event,
        "confidence": confidence,
        "note": note,
        "numbers": {
            "kills": kills,
            "assists": assists,
            "damage": damage,
        },
    }


def _build_note(kills: list, assists: list, damage: list) -> str:
    """根据 numbers 生成标准 note — 只显示伤害变化."""
    if damage[0] is not None and damage[1] is not None:
        if damage[0] != damage[1]:
            return f"伤害 {damage[0]}→{damage[1]}"
        else:
            return "数字无变化"
    return "数字模糊，无变化"


# (deprecated) 保留函数签名兼容旧调用，v2 不再使用
# detect_combat_events / compute_frame_action 已移除，战斗判断交给 LLM


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

@tool
def describe_frames(frame_dir: str, sample_count: int = 10) -> dict:
    """使用多模态 LLM 逐帧分析视频抽帧画面，生成画面内容描述。

    Args:
        frame_dir: 抽帧图片所在目录（含 frame_0001.jpg 等）
        sample_count: 均匀采样多少帧进行分析

    Returns:
        {success, frame_descriptions: [{frame, time_seconds, description}], frame_count}
    """
    frame_path = Path(frame_dir)
    if not frame_path.exists():
        return {"success": False, "error": f"目录不存在: {frame_dir}"}

    all_frames = sorted(frame_path.glob("frame_*.jpg"))
    if not all_frames:
        return {"success": False, "error": f"目录下无帧图片: {frame_dir}"}

    step = max(1, len(all_frames) // sample_count)
    sampled = all_frames[::step][:sample_count]

    try:
        llm = create_multimodal_llm(
            runtime_api_key=_get_runtime_vision_key(),
            runtime_provider=_get_runtime_vision_provider(),
            runtime_model=_get_runtime_vision_model(),
        )
    except Exception as e:
        return {"success": False, "error": f"多模态 LLM 初始化失败: {e}"}

    descriptions = []
    print(f"  ️  逐帧分析 {len(sampled)} 张图片...")
    for i, fpath in enumerate(sampled):
        try:
            frame_num = int(fpath.stem.split("_")[-1])
            b64 = _encode_image(str(fpath))
            image_url = f"data:image/jpeg;base64,{b64}"
            if (i + 1) % 5 == 0 or i == len(sampled) - 1:
                msg = f"    分析进度: {i + 1}/{len(sampled)} 帧"
                print(f"\r{msg}", end="", flush=True)
                emit_progress_overwrite(msg)

            from langchain_core.messages import HumanMessage
            msg = HumanMessage(content=[
                {
                    "type": "text",
                    "text": (
                        "请详细描述这个视频画面的视觉内容，包括：\n"
                        "1. 场景/环境（在哪里，什么类型的空间）\n"
                        "2. 画面主体（人物/物体/角色，数量，位置，正在做什么动作）\n"
                        "3. 画面中的文字/UI/HUD（如有字幕、弹幕、游戏界面等）\n"
                        "4. 光线、色彩、整体氛围\n"
                        "5. 镜头类型（特写/中景/全景/航拍/...）和构图\n"
                        "6. 画面质量（是否模糊/抖动/过曝/偏暗）\n"
                        "请用中文描述，控制在100字以内。重点描述\"画面上能看到什么\"。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_url}},
            ])
            resp = llm.invoke([msg])
            desc = resp.content.strip() if hasattr(resp, 'content') else str(resp)

            descriptions.append({
                "frame": frame_num,
                "time_seconds": 0.0,
                "description": desc,
            })
        except Exception as e:
            descriptions.append({
                "frame": int(fpath.stem.split("_")[-1]) if "_" in fpath.stem else i,
                "time_seconds": 0.0,
                "description": f"[分析失败: {str(e)[:80]}]",
            })

    print()
    return {
        "success": True,
        "frame_descriptions": descriptions,
        "frame_count": len(descriptions),
    }


# ═══════════════════════════════════════════════════════════════
#  Apex 专用：画面数据提取 + 战斗检测
# ═══════════════════════════════════════════════════════════════

def _extract_json(resp_text: str) -> str:
    """从模型返回中提取纯 JSON 字符串.

    处理：markdown fence、文字+JSON混杂、JSON在文本中间等情况.
    """
    if not resp_text or not resp_text.strip():
        raise json.JSONDecodeError("empty response", "", 0)

    # 1. 先找 ```json ... ``` 或 ``` ... ```
    fence_start = resp_text.find("```")
    if fence_start != -1:
        after = resp_text[fence_start + 3:]
        # 跳过可能的语言标记 (json) 到换行
        nl = after.find("\n")
        if nl != -1:
            json_part = after[nl + 1:]
        else:
            json_part = after
        fence_end = json_part.find("```")
        if fence_end != -1:
            return json_part[:fence_end].strip()

    # 2. 直接找第一个 { 并用括号匹配
    brace = resp_text.find("{")
    if brace == -1:
        raise json.JSONDecodeError("no JSON object found", resp_text[:200], 0)

    depth = 0
    end = -1
    for i in range(brace, len(resp_text)):
        if resp_text[i] == "{":
            depth += 1
        elif resp_text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise json.JSONDecodeError("unclosed JSON object", resp_text[brace:brace+200], 0)

    return resp_text[brace:end].strip()


@tool
def classify_frames_apex(
    frame_dir: str,
    sample_count: int = 20,
    chunk_size: int = 10,
) -> dict:
    """[DEPRECATED v1] Apex Legends 专用：逐帧读取右上角面板数字，代码检测战斗事件.

    ⚠️  v2 不再使用此工具。v2 战斗检测主线在 analyzer.py 的 _run_vision_analysis 中，
    由 LLM 直接输出 {has_combat, event, confidence} 格式，不再走 player_stats 读数 + 代码 diff 流程。

    保留此函数仅为向后兼容旧调用方，返回格式仍为 v1 的 player_stats 结构。
    新代码请使用 analyzer_node 流程。

    Args:
        frame_dir: 抽帧图片目录
        sample_count: 均匀采样帧数
        chunk_size: 每批帧数（建议 8-12，读数需要精度）

    Returns:
        {success, frame_labels: [{frame, time_seconds, player_stats, _changes, _event}], frame_count}
    """
    import warnings
    warnings.warn(
        "classify_frames_apex is deprecated (v1). "
        "Use analyzer_node workflow for v2 combat detection.",
        DeprecationWarning, stacklevel=2,
    )
    print("⚠️  [DEPRECATED] classify_frames_apex 是 v1 工具，请使用 analyzer_node (v2)")
    from langchain_core.messages import HumanMessage

    frame_path = Path(frame_dir)
    if not frame_path.exists():
        return {"success": False, "error": f"目录不存在: {frame_dir}"}

    all_frames = sorted(frame_path.glob("frame_*.jpg"))
    if not all_frames:
        return {"success": False, "error": f"目录下无帧图片: {frame_dir}"}

    # 均匀采样
    step = max(1, len(all_frames) // sample_count)
    sampled = all_frames[::step][:sample_count]

    try:
        llm = create_multimodal_llm(
            runtime_api_key=_get_runtime_vision_key(),
            runtime_provider=_get_runtime_vision_provider(),
            runtime_model=_get_runtime_vision_model(),
        )
    except Exception as e:
        return {"success": False, "error": f"多模态 LLM 初始化失败: {e}"}

    total_frames = len(sampled)
    chunks = [sampled[i:i+chunk_size] for i in range(0, total_frames, chunk_size)]
    total_chunks = len(chunks)

    # 读数需要更高分辨率
    read_px = max(settings.vision_max_px, 800)
    msg = f"   Apex 数据提取：{total_frames} 帧 → {total_chunks} 批 (分辨率 {read_px}px)"
    print(msg); emit_progress(msg)
    emit_status("️ 读取 UI 数据... 0%")

    all_labels = []

    for chunk_idx, chunk in enumerate(chunks):
        chunk_num = chunk_idx + 1
        chunk_start = chunk_idx * chunk_size + 1
        chunk_end = chunk_idx * chunk_size + len(chunk)
        pct = round(chunk_num / total_chunks * 100)

        human_text = VISION_APEX_HUMAN.format(
            frame_count=len(chunk),
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )
        content_parts = [{"type": "text", "text": human_text}]

        chunk_size_kb = 0
        for fpath in chunk:
            b64 = _encode_image(str(fpath), max_px=read_px)
            chunk_size_kb += len(b64)
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        msg = f"   批次 {chunk_num}/{total_chunks} ({chunk_start}-{chunk_end} 帧, {chunk_size_kb/1024:.0f}KB)..."
        print(f"\r{msg}", end="", flush=True); emit_progress_overwrite(msg)

        try:
            resp = llm.invoke([
                HumanMessage(content=[
                    {"type": "text", "text": VISION_APEX_SYSTEM},
                    *content_parts,
                ])
            ])
            resp_text = resp.content.strip() if hasattr(resp, 'content') else str(resp)
            json_str = _extract_json(resp_text)
            result = json.loads(json_str)
            raw_frames = result.get("frames", [])
            # 兼容：模型可能没包 frames 数组，直接返回单帧对象或帧列表
            if not raw_frames:
                if isinstance(result, list):
                    raw_frames = result  # [{frame:1,...}, {frame:2,...}]
                elif isinstance(result, dict) and "frame" in result:
                    raw_frames = [result]  # 单帧对象 {frame:1,...}

            for item in raw_frames:
                idx = item.get("frame", 0) - 1
                if 0 <= idx < len(chunk):
                    fpath = chunk[idx]
                    frame_num = int(fpath.stem.split("_")[-1])
                    all_labels.append({
                        "frame": frame_num,
                        "time_seconds": 0.0,
                        "player_stats": item.get("player_stats", {}),
                    })

            msg = f"   批次 {chunk_num}/{total_chunks} 完成 ({len(raw_frames)} 帧)"
            if len(raw_frames) == 0:
                # debug: 模型可能没理解格式，打印前 300 字符
                snippet = resp_text[:300].replace("\n", "\\n")
                msg += f" [DEBUG: {snippet}]"
            print(f"\r{msg}"); emit_progress_overwrite(msg)

        except json.JSONDecodeError as e:
            #  重试：JSON 解析失败时再问一次，加强指令
            msg = f"  ️ 批次 {chunk_num} JSON 解析失败，重试中..."
            print(f"\r{msg}"); emit_progress_overwrite(msg)
            try:
                retry_parts = [{"type": "text", "text": "上轮返回格式有误。请严格只返回 JSON：{\"frames\": [...]}"}]
                retry_parts.extend(content_parts[1:])  # 图片部分不动
                resp2 = llm.invoke([HumanMessage(content=retry_parts)])
                resp_text2 = resp2.content.strip() if hasattr(resp2, 'content') else str(resp2)
                json_str2 = _extract_json(resp_text2)
                result2 = json.loads(json_str2)
                raw_frames2 = result2.get("frames", [])
                if not raw_frames2:
                    if isinstance(result2, list):
                        raw_frames2 = result2
                    elif isinstance(result2, dict) and "frame" in result2:
                        raw_frames2 = [result2]
                for item in raw_frames2:
                    idx = item.get("frame", 0) - 1
                    if 0 <= idx < len(chunk):
                        fpath = chunk[idx]
                        frame_num = int(fpath.stem.split("_")[-1])
                        all_labels.append({
                            "frame": frame_num, "time_seconds": 0.0,
                            "player_stats": item.get("player_stats", {}),
                        })
                msg = f"   批次 {chunk_num}/{total_chunks} 重试成功 ({len(raw_frames2)} 帧)"
                print(f"\r{msg}"); emit_progress_overwrite(msg)
            except Exception:
                msg = f"   批次 {chunk_num} 重试也失败，丢弃 ({len(chunk)} 帧数据丢失)"
                print(f"\r{msg}"); emit_progress_overwrite(msg)
                for fpath in chunk:
                    frame_num = int(fpath.stem.split("_")[-1])
                    all_labels.append({
                        "frame": frame_num, "time_seconds": 0.0,
                        "player_stats": {},
                        
                    })
        except Exception as e:
            msg = f"  ️ 批次 {chunk_num} 请求失败: {str(e)[:100]}"
            print(f"\r{msg}"); emit_progress_overwrite(msg)
            for fpath in chunk:
                frame_num = int(fpath.stem.split("_")[-1])
                all_labels.append({
                    "frame": frame_num, "time_seconds": 0.0,
                    "player_stats": {},
                })

        # 更新百分比进度
        emit_status(f"️ 读取 UI 数据... {pct}%")

    # ── 按帧号排序 ──
    all_labels.sort(key=lambda x: x["frame"])

    # ── (deprecated) v1 的 detect_combat_events 已移除，战斗判断交给 LLM ──

    # ── 统计（新字段）──
    combat_frames = sum(1 for l in all_labels if l.get("has_combat"))
    kill_frames = sum(1 for l in all_labels if l.get("event") == "kill")
    msg = (
        f"   完成: {len(all_labels)} 帧 | "
        f"战斗={combat_frames} 击杀={kill_frames}"
    )
    print(msg); emit_progress(msg)

    return {
        "success": True,
        "frame_labels": all_labels,
        "frame_count": len(all_labels),
    }


# 导出
VISION_TOOLS = [
    describe_frames,
    classify_frames_apex,
]
