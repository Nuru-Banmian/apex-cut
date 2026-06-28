"""导演 Agent — 需求理解（对话模式供 API 调用）+ 工作流透传.

Director 不再生成 segment_strategy。裁决策日后由 Editor 中的 LLM 直接负责。
当前职责：对话模式下帮用户澄清需求；工作流中透传用户输入。
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
# Apex Legends 领域知识
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

## 可检测的事件
- damage_dealt: 累计伤害数字增加 ≥ 阈值（唯一战斗信号，通过帧间伤害差值检测）

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
# Director 对话 Prompt（前端聊天用）
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

## Apex 剪辑核心决策点
1. 要什么？所有战斗 / 只要高光时刻？
2. 不要什么？舔包搜刮 / 跑图转点 / 跳伞选人 / 死亡回放？
3. 节奏？快节奏高光（紧凑衔接）/ 完整叙事线（保留前后铺垫）？
4. 目标时长？1-2分钟 / 3-5分钟 / 不限制？

## 核心规则
- **总共最多 2 轮提问**，第 2 轮后必须出方案
- **尽量第 1 轮一次问完**
- 客户需求明确 → 直接出方案，不凑轮数

## 输出 JSON

提问阶段：
{{
    "phase": "questions",
    "message": "简短招呼",
    "current_understanding": "你目前对需求的理解（2-3句）",
    "questions": [
        {{"id": "q0", "text": "要不要保留所有战斗，还是只要高光时刻？"}},
        {{"id": "q1", "text": "要不要删舔包搜刮？"}}
    ]
}}

出方案阶段（需求已明确 / 已达第2轮）：
{{
    "phase": "plan",
    "message": "方案摘要",
    "edit_style": "快节奏高光集锦/完整叙事线/教学复盘",
    "editing_notes": "剪辑要点（2-3句）",
    "plan_summary": "用户需求→剪辑方向→关键决策"
}}

只返回 JSON。"""


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
            return {
                "phase": "plan",
                "message": result.get("message", ""),
                "content_type": "apex",
                "content_type_name": "Apex Legends",
                "edit_style": result.get("edit_style", ""),
                "editing_notes": result.get("editing_notes", ""),
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
# Director 节点（LangGraph 入口）— 透传用户需求
# ═══════════════════════════════════════════════════════════════

def director_node(state: VideoEditState) -> dict:
    """导演节点 — 透传用户需求，不做策略翻译."""
    requirement = state.get("user_requirement", "")
    video_path = state.get("video_path", "")

    print(f"\n{'='*60}")
    print(f"[ 导演] 需求: {requirement[:120]}")
    print(f"{'='*60}")
    emit_progress(" 理解需求...")

    if not requirement.strip():
        return {
            "user_requirement": requirement,
            "content_type": "apex",
            "target_duration": None,
            "target_aspect_ratio": None,
        }

    return {
        "user_requirement": requirement,
        "content_type": "apex",
    }
