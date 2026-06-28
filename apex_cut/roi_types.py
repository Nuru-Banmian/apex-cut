"""ROI 类型定义 — 用户框选的画面区域类型与 LLM 指令模板.

设计原则:
  - 类型定义纯数据，不含位置信息（位置由用户在前端拖框决定）
  - 每种类型对应一条 LLM 指令，告诉多模态 LLM 在这个裁图区域里找什么
  - 所有游戏通用 — 不写死 Apex/Valorant/CS2 的游戏知识
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# ROI 类型定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoiType:
    """ROI 类型 — 定义"这个框看什么"."""
    id: str           # 唯一标识，如 "kills_assists" / "total_damage"
    name: str         # 中文名，如 "累计统计数字"
    icon: str         # emoji
    instruction: str  # LLM 指令 — 告诉视觉LLM在这个裁图区域里找什么


# ── 3 种预设类型 ──

ROI_TYPES: list[RoiType] = [
    RoiType(
        id="kills_assists",
        name="击杀/助攻",
        icon="💀",
        instruction=(
            "读这个区域里的击杀数和助攻数，两个独立的数字。\n"
            "只报告数字值，格式：「击杀=X, 助攻=Y」。\n"
            "看不清填 null，不要猜。\n"
            "注意：这些是累计值（本局从开局到现在的总和），不是这一帧发生的事。\n"
            "数字大小本身不说明这一帧有没有打架——"
            "只有跟相邻帧对比，数字增加了才说明有事件。"
        ),
    ),
    RoiType(
        id="total_damage",
        name="累计伤害",
        icon="📊",
        instruction=(
            "读这个区域里的累计伤害数字。通常是一个较大的数值（可能三位数或四位数）。\n"
            "只报告数字值，格式：「累计伤害=N」。\n"
            "看不清填 null，不要猜。\n"
            "注意：这是累计值，不是这一帧打出的伤害。伤害=500 只说明整局打了 500，\n"
            "不说明这一帧在打架。跟相邻帧对比，差值才是这个间隔内打出的伤害。"
        ),
    ),
    RoiType(
        id="kill_feed",
        name="击杀/击倒文字提示",
        icon="☠️",
        instruction=(
            "这个区域里有没有击杀或击倒的文字通知？\n"
            "通常在屏幕左上角或中央偏上的消息流区域，格式类似：\n"
            "「玩家A [武器图标] 玩家B」或「玩家A 淘汰了 玩家B」。\n"
            "报告：「类型=击倒/击杀/无, 内容=...」。\n"
            "多条消息依次列出。没有就报告「无」。\n"
            "出现击杀/击倒文字 = 刚发生了击杀事件。"
        ),
    ),
]

# id → RoiType 快速查找
ROI_TYPE_MAP: dict[str, RoiType] = {t.id: t for t in ROI_TYPES}


# ═══════════════════════════════════════════════════════════════
# ROI 实例 — 用户实际框选的一个区域
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoiInstance:
    """用户框选的一个 ROI 实例（类型 + 位置 + 自定义指令）."""
    type_id: str             # ROI 类型 ID（kills_assists / total_damage / ...）
    rect: dict               # {x, y, w, h} 百分比坐标 (0.0~1.0)
    label: str = ""          # 用户起的名字（可选，如"右上统计面板"）
    custom_instruction: str = ""  # 自定义指令（可覆盖类型的默认 instruction）

    @property
    def instruction(self) -> str:
        """获取实际生效的 LLM 指令（自定义优先，否则用类型默认）."""
        if self.custom_instruction.strip():
            return self.custom_instruction.strip()
        t = ROI_TYPE_MAP.get(self.type_id)
        return t.instruction if t else ""

    @property
    def type_name(self) -> str:
        """获取类型中文名."""
        t = ROI_TYPE_MAP.get(self.type_id)
        return t.name if t else "未知"

    @property
    def type_icon(self) -> str:
        """获取类型图标."""
        t = ROI_TYPE_MAP.get(self.type_id)
        return t.icon if t else "❓"

    def to_dict(self) -> dict:
        return {
            "type_id": self.type_id,
            "type_name": self.type_name,
            "type_icon": self.type_icon,
            "rect": self.rect,
            "label": self.label,
            "custom_instruction": self.custom_instruction,
            "instruction": self.instruction,
        }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def hash_roi_config(rois: list[RoiInstance]) -> str:
    """计算 ROI 配置指纹（用于缓存匹配）."""
    data = json.dumps(
        [{"type_id": r.type_id, "rect": r.rect, "instruction": r.instruction}
         for r in rois],
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(data.encode()).hexdigest()[:12]


def roi_config_from_list(raw: list[dict]) -> list[RoiInstance]:
    """从 JSON 列表反序列化 ROI 配置."""
    return [
        RoiInstance(
            type_id=r.get("type_id", "kills_assists"),
            rect=r.get("rect", {}),
            label=r.get("label", ""),
            custom_instruction=r.get("custom_instruction", ""),
        )
        for r in raw
    ]


def roi_config_to_list(rois: list[RoiInstance]) -> list[dict]:
    """序列化 ROI 配置为 JSON 列表."""
    return [r.to_dict() for r in rois]


# ═══════════════════════════════════════════════════════════════
# ⚠️ COMBAT_ANALYSIS_SYSTEM 已废弃 — 战斗判断 Prompt 在 analyzer.py 中
# 详见 ROI_COMBAT_SYSTEM / DEFAULT_COMBAT_SYSTEM
# ═══════════════════════════════════════════════════════════════
