"""导演 Agent — Apex Legends 专用策略翻译器.

Director 不再输出软约束枚举，而是把用户需求翻译成精确的可执行规则。
下游 Editor 拿到 segment_strategy 后直接机械执行，不依赖 LLM。

策略字段:
  - triggers: 什么事件触发保留（damage_dealt / kill_occurred / assist_occurred / in_combat）
  - min_damage: 伤害增量阈值（默认 50）
  - padding_before / padding_after: 触发点前后包多少秒
  - merge_gap: 两个片段多近就合并
  - min_segment: 片段最小时长
  - order: chronological（时间序）/ priority（精彩度降序）
  - trim_strategy: cut_lowest_priority（按权重裁）/ none（全保留）
  - priority_weights: 各事件类型的价值权重
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from apex_cut.state import VideoEditState
from apex_cut.config import create_llm, _extract_runtime_keys
from apex_cut.errors import check_and_raise
from apex_cut.sse import emit_progress


# ═══════════════════════════════════════════════════════════════
# Apex Legends 领域知识（硬编码）
# ═══════════════════════════════════════════════════════════════

APEX_KNOWLEDGE = """
## Apex Legends 一局时间线
1. 选人+跳伞 (30s-2min) — 英雄选择界面 + 空中下落
2. 落地搜刮 (2-5min) — 捡枪捡甲，无战斗
3. 首次交火 (30s-2min) — 落地打架，核心素材
4. 转点跑图 (1-3min) × N — 滑铲跑步，无战斗
5. 舔包补给 (30s-1min) × N — 死亡盒UI覆盖画面
6. 中后期团战 (1-3min) × N — 3v3/多队混战，核心素材
7. 决赛圈 (1-5min) — 多队高压，最高张力
8. 胜利/死亡画面 (10-30s)

## 可检测的事件（通过右上角面板数字变化检测）
- kill_occurred: 人头数+1
- assist_occurred: 助攻数+1
- damage_dealt: 伤害数字增加 ≥ 阈值（正在交火）
- in_combat: 以上任一事件发生（最宽泛的战斗信号）

## 可排除的场景
- dropship: 英雄选择 / 跳伞画面
- death_cam: 观战/死亡回放/结算
- looting: 死亡盒/补给箱物品栏 UI
- loading: 纯黑/加载画面
- menu: 背包界面 / 大地图
"""


def _load_capabilities() -> str:
    """读取 SYSTEM_CAPABILITIES.md 关键段落."""
    cap_path = Path(__file__).parent / "SYSTEM_CAPABILITIES.md"
    if not cap_path.exists():
        return ""
    try:
        text = cap_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        sections: list[str] = []
        in_target = False
        for line in lines:
            if any(kw in line for kw in ["##  系统能做到的", "##  系统做不到的"]):
                in_target = True
                sections.append(line)
            elif in_target and line.startswith("## ") and not any(
                kw in line for kw in ["能做", "做不到"]
            ):
                in_target = False
            elif in_target:
                sections.append(line)
        return "\n".join(sections).strip()
    except Exception:
        return ""


SYSTEM_CAPABILITIES = _load_capabilities()


# ═══════════════════════════════════════════════════════════════
# Director 对话 Prompt（多轮讨论）
# ═══════════════════════════════════════════════════════════════

DIRECTOR_CHAT_PROMPT = """你是 Apex Legends 剪辑导演，正在和客户确认这局游戏的剪辑需求。

## 客户初始需求
{user_requirement}

## 对话历史
{conversation_history}

## 当前状态
第 {round_num} 轮对话

## ️ 系统能力边界
{system_capabilities}

## 核心规则
- **总共最多 2 轮提问**，第 2 轮后必须出方案
- **尽量第 1 轮一次问完**
- 客户需求明确 → 直接出方案，不凑轮数

## Apex 剪辑核心决策点（优先确认）
1. 要什么？所有战斗 / 只要击杀 / 要完整一整局？
2. 不要什么？舔包搜刮 / 跑图转点 / 跳伞选人 / 死亡回放？
3. 节奏？快节奏高光（紧凑衔接）/ 完整叙事线（保留前后铺垫）？
4. 目标时长？1-2分钟 / 3-5分钟 / 不限制？

## 输出 JSON

提问阶段：
{{
    "phase": "questions",
    "message": "简短招呼",
    "current_understanding": "你目前对需求的理解（2-3句）",
    "questions": [
        {{"id": "q0", "text": "要不要保留所有击杀，还是只要高光时刻？"}},
        {{"id": "q1", "text": "要不要删舔包搜刮？"}}
    ]
}}

出方案阶段（需求已明确 / 已达第2轮）：
{{
    "phase": "plan",
    "message": "方案摘要",
    "segment_strategy": {{
        "triggers": ["kill_occurred", "assist_occurred", "damage_dealt"],
        "min_damage": 50,
        "padding_before": 15,
        "padding_after": 10,
        "merge_gap": 8,
        "min_segment": 3,
        "order": "priority",
        "trim_strategy": "cut_lowest_priority",
        "priority_weights": {{
            "kill_occurred": 5,
            "assist_occurred": 3,
            "damage_dealt": 1,
            "in_combat": 1
        }}
    }},
    "edit_style": "快节奏高光集锦/完整叙事线/教学复盘",
    "editing_notes": "剪辑要点（2-3句）",
    "review_criteria": [{{"check": "检查项", "pass_condition": "通过条件"}}],
    "plan_summary": "结构→风格→关键决策"
}}

只返回 JSON。"""


# ═══════════════════════════════════════════════════════════════
# Director 主 Prompt（一次出可执行策略）
# ═══════════════════════════════════════════════════════════════

DIRECTOR_SYSTEM_PROMPT = """你是 Apex Legends 专属剪辑策略师。
把用户的剪辑需求翻译成**精确可执行规则**，下游 Agent 会机械执行你的规则。

{apex_knowledge}

## ️ 系统能力边界
{system_capabilities}

## ️ 用户核心需求（不可违背）
{user_requirement}

---
## 翻译规则

###  triggers（触发条件 — 什么事件值得保留）

可用触发事件（系统通过右上角面板数字变化检测）：
- `damage_dealt` — 伤害数字增加 ≥ 阈值（**最即时的交火信号**，伤害一跳就触发）
- `kill_occurred` — 人头数+1（击倒→补掉后滞后确认，比实际战斗晚数秒）
- `assist_occurred` — 助攻数+1（参与击杀但非最后一枪）
- `in_combat` — 以上任一发生（最宽泛）

翻译对照：
- 用户说"所有战斗""战斗片段""打架的" → triggers: ["damage_dealt", "kill_occurred"],
  或直接用 ["damage_dealt"] 加低 min_damage（伤害增量是最直接的战斗信号）
- 用户说"击杀集锦""只要击杀" → triggers: ["kill_occurred", "damage_dealt"]（保证有人头入手也有战斗过程）
- 用户说"精彩操作""高光时刻" → triggers: ["damage_dealt", "kill_occurred", "assist_occurred"]
- 用户说"完整对局""整局" → triggers: ["damage_dealt", "kill_occurred", "assist_occurred"]

`min_damage`: 伤害增量阈值，默认 50。用户说"只要明显交火"可提到 80，"任何摩擦都要"降到 30。

### ️ padding_before / padding_after（战斗前后的铺垫和收尾保留多少秒）

- "快节奏""紧凑""不要废话" → before: 10-15, after: 5-10
- "完整战斗过程""保留前后" → before: 25-35, after: 25-35
- "保留战术决策/交流" → before: 20-30, after: 15-20
- 默认（没特别说） → before: 20, after: 20

###  merge_gap（两个战斗片段间隔多少秒以内就合并成一个）

- "快节奏""不要断""紧凑" → 10-15s（合得更激进）
- "分开每场战斗""独立片段" → 3-5s
- 默认 → 8-10s

###  order（排序方式）

- "精彩前置""高光先放""钩子开场" → `priority`（按 priority_weights 得分降序）
- "时间顺序""完整叙事""按流程" → `chronological`
- 默认 → `chronological`

### ️ trim_strategy（有目标时长时怎么裁）

- 有目标时长 → `cut_lowest_priority`（按 priority_weights 裁掉低分片段）
- 无目标时长 → `none`（全保留）

### ️ priority_weights（事件价值权重，用于排序和/或裁剪）

默认权重（伤害是最即时的交火信号，与人头同级）:
- damage_dealt: 5（伤害增量 = 正在交火的直接证据）
- kill_occurred: 5（人头确认，但比实际战斗滞后）
- assist_occurred: 2（参与击杀，价值较低）
- in_combat: 1（兜底）

###  min_segment

默认 3 秒。用户说"不要短片段"可提到 5。

---
## 输出 JSON

{{
    "segment_strategy": {{
        "triggers": ["kill_occurred", "assist_occurred", "damage_dealt"],
        "min_damage": 50,
        "padding_before": 20,
        "padding_after": 20,
        "merge_gap": 8,
        "min_segment": 3,
        "order": "chronological",
        "trim_strategy": "cut_lowest_priority",
        "priority_weights": {{
            "kill_occurred": 5,
            "assist_occurred": 3,
            "damage_dealt": 1,
            "in_combat": 1
        }}
    }},
    "edit_style": "快节奏高光集锦/完整叙事线/教学复盘",
    "editing_notes": "Apex 剪辑要点（2-3句，提及触发条件和片段策略）",
    "review_criteria": [
        {{"check": "检查项", "pass_condition": "通过条件"}}
    ],
    "plan_summary": "触发条件→padding→排序→时长策略"
}}

## 规则
1. segment_strategy 的每个字段都必须填，不要省略
2. triggers 不能为空
3. priority_weights 至少包含你选择的 triggers 对应的权重
5. 只返回 JSON"""


# ═══════════════════════════════════════════════════════════════
# Director 对话模式（供 API 调用）
# ═══════════════════════════════════════════════════════════════

def director_chat(state: VideoEditState, messages: list[dict], answers: dict | None = None) -> dict:
    """Apex 导演对话模式 — 2 轮讨论，一次问清需求后出方案."""
    requirement = state.get("user_requirement", "")

    history_parts = []
    for m in messages:
        role_label = "导演" if m.get("role") == "director" else "客户"
        history_parts.append(f"{role_label}: {m.get('content', '')}")

    if answers:
        answer_lines = ["客户逐题回答："]
        question_map = {}
        for m in messages:
            if m.get("role") == "director" and m.get("questions"):
                for q in m["questions"]:
                    qid = q.get("id", "") if isinstance(q, dict) else ""
                    qtext = q.get("text", "") if isinstance(q, dict) else str(q)
                    if qid:
                        question_map[qid] = qtext
        for qid, ans in answers.items():
            qtext = question_map.get(qid, qid)
            answer_lines.append(f"  - Q: {qtext} → A: {ans}")
        history_parts.append("\n".join(answer_lines))

    history_text = "\n".join(history_parts) if history_parts else "（首次对话）"

    director_turns = sum(1 for m in messages if m.get("role") == "director")
    current_round = director_turns + 1
    force_plan = current_round > 2

    try:
        provider, api_key, api_base, model = _extract_runtime_keys(state)
        llm = create_llm(
            temperature=0.3, runtime_provider=provider,
            runtime_api_key=api_key, runtime_base_url=api_base,
            runtime_model=model,
        )

        override = ""
        if force_plan:
            override = "\n\n## ️️️ 已达提问上限（2轮）！本轮必须输出 phase=plan，禁止再提问！"

        sys_prompt = DIRECTOR_CHAT_PROMPT.format(
            user_requirement=requirement,
            conversation_history=history_text,
            round_num=current_round,
            system_capabilities=SYSTEM_CAPABILITIES,
        ) + override

        response = llm.invoke([
            SystemMessage(content=sys_prompt),
            HumanMessage(content="视频类型: Apex Legends 游戏录像"),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        result = json.loads(content)
        phase = result.get("phase", "plan")

        if force_plan and phase in ("questions", "question"):
            print(f"[ 对话] 已达2轮上限，强制生成方案...")
            try:
                plan_response = llm.invoke([
                    SystemMessage(content="你是 Apex Legends 剪辑导演。根据讨论，输出最终方案的 JSON。"),
                    HumanMessage(content=f"## 客户需求\n{requirement}\n\n## 讨论\n{history_text}\n\n只返回 JSON。"),
                ])
                plan_content = plan_response.content if hasattr(plan_response, "content") else str(plan_response)
                plan_content = plan_content.strip()
                if plan_content.startswith("```"):
                    plan_content = plan_content.split("\n", 1)[1].rsplit("\n```", 1)[0]
                result = json.loads(plan_content)
                result["phase"] = "plan"
                phase = "plan"
            except Exception:
                pass

        raw_questions = result.get("questions", [])
        questions: list[dict] = []
        for i, q in enumerate(raw_questions):
            if isinstance(q, dict):
                if "id" not in q:
                    q["id"] = f"q{i}"
                questions.append(q)
            elif isinstance(q, str):
                questions.append({"id": f"q{i}", "text": q})

        if phase in ("questions", "question"):
            return {
                "phase": "questions",
                "message": result.get("message", ""),
                "current_understanding": result.get("current_understanding", ""),
                "questions": questions,
                "content_type": "apex",
            }
        else:
            strategy = result.get("segment_strategy") or _fallback_strategy()
            return {
                "phase": "plan",
                "message": result.get("message", ""),
                "content_type": "apex",
                "content_type_name": "Apex Legends",
                "segment_strategy": strategy,
                "edit_style": result.get("edit_style", ""),
                "editing_notes": result.get("editing_notes", ""),
                "review_criteria": result.get("review_criteria") or _fallback_review_criteria(),
                "plan_summary": result.get("plan_summary", ""),
            }

    except json.JSONDecodeError:
        return {
            "phase": "questions", "message": "方案生成异常，请重试",
            "questions": [{"id": "q0", "text": "请描述你的 Apex 剪辑需求（如：保留所有战斗、删跑图舔包、快节奏）"}],
            "current_understanding": "", "content_type": "apex",
        }
    except Exception as e:
        check_and_raise(e, "导演对话")
        return {
            "phase": "questions", "message": f"出错了: {str(e)[:100]}",
            "questions": [], "current_understanding": "", "content_type": "apex",
        }


# ═══════════════════════════════════════════════════════════════
# Director 节点（LangGraph 入口）
# ═══════════════════════════════════════════════════════════════

def director_node(state: VideoEditState) -> dict:
    """Apex 导演节点 — 分析需求 → 生成可执行策略."""
    requirement = state.get("user_requirement", "")
    video_path = state.get("video_path", "")

    if state.get("director_plan_confirmed"):
        print(f"\n[ 导演]  用户已确认方案，跳过")
        return {}

    print(f"\n{'='*60}")
    print(f"[ 导演]  Apex Legends — 策略翻译")
    print(f"[ 导演] 需求: {requirement}")
    print(f"{'='*60}")
    emit_progress(" 翻译需求为可执行策略...")

    if not requirement.strip():
        return {
            "user_requirement": requirement,
            "content_type": "apex",
            "segment_strategy": _fallback_strategy(),
            "target_duration": None,
            "target_aspect_ratio": None,
        }

    try:
        provider, api_key, api_base, model = _extract_runtime_keys(state)
        llm = create_llm(
            temperature=0.3, runtime_provider=provider,
            runtime_api_key=api_key, runtime_base_url=api_base,
            runtime_model=model,
        )

        sys_prompt = DIRECTOR_SYSTEM_PROMPT.format(
            user_requirement=requirement,
            apex_knowledge=APEX_KNOWLEDGE,
            system_capabilities=SYSTEM_CAPABILITIES,
        )

        response = llm.invoke([
            SystemMessage(content=sys_prompt),
            HumanMessage(content=f"## 视频\n{video_path}\n\n## 类型\nApex Legends 游戏录像"),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        plan = json.loads(content)

        strategy = plan.get("segment_strategy")
        if not strategy or not strategy.get("triggers"):
            strategy = _fallback_strategy()
            print(f"[ 导演] ️ LLM 未返回有效策略，使用默认")

        rc = plan.get("review_criteria")
        if not rc:
            rc = _fallback_review_criteria()

        triggers_str = ", ".join(strategy.get("triggers", []))
        print(f"[ 导演] 触发: {triggers_str}")
        print(f"[ 导演] padding: 前{strategy.get('padding_before')}s 后{strategy.get('padding_after')}s")
        print(f"[ 导演] merge: {strategy.get('merge_gap')}s gap, min {strategy.get('min_segment')}s")
        print(f"[ 导演] 排序: {strategy.get('order')}, 裁剪: {strategy.get('trim_strategy')}")
        print(f"[ 导演] 风格: {plan.get('edit_style', '')}")

        return {
            "user_requirement": requirement,
            "content_type": "apex",
            "target_duration": plan.get("target_duration"),
            "target_aspect_ratio": plan.get("target_aspect_ratio"),
            "segment_strategy": strategy,
            "director_plan_summary": plan.get("plan_summary", ""),
            "edit_style": plan.get("edit_style", ""),
            "editing_notes": plan.get("editing_notes", ""),
            "review_criteria": rc,
        }

    except json.JSONDecodeError as e:
        print(f"[ 导演] JSON 解析失败: {e}")
        return _fallback(requirement)
    except Exception as e:
        check_and_raise(e, "导演")
        print(f"[ 导演] LLM 失败: {e}")
        return _fallback(requirement)


# ═══════════════════════════════════════════════════════════════
# 保底策略
# ═══════════════════════════════════════════════════════════════

def _fallback_strategy() -> dict:
    """默认策略：保留所有战斗 + 排除非战斗场景."""
    return {
        "triggers": ["in_combat", "kill_occurred", "assist_occurred", "damage_dealt"],
        "min_damage": 30,
        "padding_before": 20,
        "padding_after": 20,
        "merge_gap": 8,
        "min_segment": 3,
        "order": "priority",
        "trim_strategy": "cut_lowest_priority",
        "priority_weights": {
            "damage_dealt": 5,
            "kill_occurred": 5,
            "assist_occurred": 2,
            "in_combat": 1,
        },
    }


def _fallback_review_criteria() -> list[dict]:
    return [
        {"check": "战斗事件是否全部覆盖", "pass_condition": "所有触发事件对应的帧都被 segment 囊括"},
        {"check": "排除场景是否被裁掉", "pass_condition": "无 dropship/death_cam/looting/loading/menu 画面"},
        {"check": "目标时长是否大致满足", "pass_condition": "输出总时长在目标的 ±20% 内"},
    ]


def _fallback(requirement: str) -> dict:
    """LLM 不可用时的保底."""
    return {
        "user_requirement": requirement,
        "content_type": "apex",
        "target_duration": None,
        "target_aspect_ratio": None,
        "segment_strategy": _fallback_strategy(),
        "director_plan_summary": requirement,
        "edit_style": "快节奏高光集锦",
        "editing_notes": "保留所有战斗，排除跑图舔包跳伞，精彩前置",
        "review_criteria": _fallback_review_criteria(),
    }
