"""审核 Agent — 纯代码查漏 + LLM 辅助判断边界/误判.

检查维度:
  1. 遗漏检查（纯代码，100% 准确）: 每个 kill 事件是否被覆盖
  2. 误判检查（LLM）: 片段是否不含任何有价值事件
  3. 边界检查（LLM）: 片段边界是否合理
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from apex_cut.state import VideoEditState
from apex_cut.config import create_llm, _extract_runtime_keys, settings
from apex_cut.errors import check_and_raise
from apex_cut.sse import emit_progress, emit_status


# ═══════════════════════════════════════════════════════════════
# 维度 1: 遗漏检查 — 纯代码（零 LLM 成本，100% 准确）
# ═══════════════════════════════════════════════════════════════

def _check_coverage(edit_plan: list[dict], frame_labels: list[dict]) -> list[dict]:
    """检查每次 kill 事件是否被至少一个片段覆盖.

    覆盖判定: 事件时间 t 满足 seg.start ≤ t ≤ seg.end
    """
    # 提取击杀事件
    kill_events = []
    for f in frame_labels:
        event_type = f.get("_event") or ""
        if event_type == "kill":
            kill_events.append({
                "time": f.get("time_seconds", 0),
                "event": "kill",
            })

    if not kill_events:
        return []

    missed = []
    for ke in kill_events:
        t = ke["time"]
        covered = any(seg["start"] <= t <= seg["end"] for seg in edit_plan)
        if not covered:
            missed.append({
                "time": t,
                "event": ke["event"],
                "reason": f"击杀事件 {t:.1f}s 未被任何片段覆盖",
            })

    if missed:
        print(f"[📋 审核] ❌ 遗漏 {len(missed)}/{len(kill_events)} 个击杀事件")
    else:
        print(f"[📋 审核] ✅ 全部 {len(kill_events)} 个击杀事件已覆盖")

    return missed


# ═══════════════════════════════════════════════════════════════
# 维度 2 & 3: 误判 + 边界 — LLM 辅助（可选，失败不影响判定）
# ═══════════════════════════════════════════════════════════════

REVIEW_LLM_SYSTEM = """你是 Apex Legends 剪辑质检员。
检查 Editor 的片段方案，但只能基于你实际看到的数据判断。

## ⚠️ 你能看到的数据
每个片段只有: start, end, events 列表, score。
已知 events: kill(击杀), assist(助攻), combat(交火)。
你**看不到**场景类型。不要猜测或编造"舔包""跑图""选人""跳伞"。

## ★ 重要：长片段是正常的
当多个击杀发生在短时间内，Editor 会把它们合并成一个长片段。
例如 3 个击杀在 520s/540s/580s → 合并为 [500, 600]=100s。这是**正确行为**，不要报 boundary_issue。
只有片段确实无效时才报 false_positive。

## 检查项

### 误判（false_positive）— 会导致拒绝
- 片段 events 为空 → false_positive
- 片段时长 > 60s 且 events 只有 combat（无 kill/assist）→ false_positive

### 边界问题（boundary）— 仅供参考，不会导致拒绝
- 片段 > 120s 且只有 1 个 kill → 可以提一句
- 其他边界顾虑可以直接放 summary 里，不要单独报 boundary_issue

## 输出 JSON
{{
  "false_positives": [],
  "boundary_issues": [],
  "summary": ""
}}

规则：只返回 JSON，没问题就全空数组。segment_index 是 1-based。"""


def _llm_quality_check(edit_plan: list[dict], strategy: dict, state: dict) -> dict:
    """LLM 检查误判和边界（失败不影响核心判定）."""
    if not edit_plan:
        return {"false_positives": [], "boundary_issues": [], "summary": ""}

    try:
        provider, api_key, api_base, text_model = _extract_runtime_keys(state)
        llm = create_llm(
            temperature=0.1, runtime_provider=provider,
            runtime_api_key=api_key, runtime_base_url=api_base,
            runtime_model=text_model,
        )

        # 构建输入
        lines = [
            f"## 策略参数",
            f"padding_before={strategy.get('padding_before', 20)}s",
            f"padding_after={strategy.get('padding_after', 20)}s",
            "",
            "## 片段列表",
        ]
        for i, seg in enumerate(edit_plan):
            lines.append(
                f"  [{i+1}] {seg['start']:.0f}s-{seg['end']:.0f}s "
                f"({seg['end']-seg['start']:.0f}s) | "
                f"events={seg.get('events', [])} | "
                f"score={seg.get('score', 0)}"
            )

        response = llm.invoke([
            SystemMessage(content=REVIEW_LLM_SYSTEM),
            HumanMessage(content="\n".join(lines)),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        result = json.loads(content)
        print(f"[📋 审核] LLM 质检: {len(result.get('false_positives', []))} 误判, "
              f"{len(result.get('boundary_issues', []))} 边界问题")
        return result

    except Exception as e:
        print(f"[📋 审核] LLM 质检失败（不影响）: {e}")
        return {"false_positives": [], "boundary_issues": [], "summary": ""}


# ═══════════════════════════════════════════════════════════════
# Reviewer 节点
# ═══════════════════════════════════════════════════════════════

def reviewer_node(state: VideoEditState) -> dict:
    """审核节点 — 纯代码查漏 + LLM 辅助质检."""
    review_round = state.get("review_round", 0)
    edit_plan = state.get("edit_plan", [])
    frame_labels = state.get("frame_labels", [])
    strategy = state.get("segment_strategy") or {}

    max_rounds = state.get("max_review_rounds") or settings.max_review_rounds
    is_last_round = review_round >= max_rounds

    keep_count = len(edit_plan)
    seg_total = sum(s["end"] - s["start"] for s in edit_plan) if edit_plan else 0

    print(f"\n{'='*60}")
    print(f"[📋 审核] 第 {review_round} 轮" + (" [最后一轮]" if is_last_round else ""))
    print(f"[📋 审核] {keep_count} 段, {seg_total:.0f}s — 检查遗漏和误判")
    print(f"{'='*60}")
    emit_status(f"📋 审核中... (第{review_round}轮)")
    emit_progress(f"━━━ 📋 审核 Agent 第 {review_round} 轮 ━━━")

    if not edit_plan:
        print(f"[📋 审核] ⚠️ 空方案，不通过")
        return {
            "review_score": 0.0,
            "review_issues": ["方案为空，无任何片段"],
            "review_approved": False,
            "plan_approved": False,
            "review_round": review_round,
        }

    if not frame_labels:
        print(f"[📋 审核] ⚠️ 无 frame_labels 数据，跳过审核")
        return {
            "review_score": 100.0,
            "review_issues": [],
            "review_approved": True,
            "plan_approved": True,
            "review_round": review_round,
        }

    # ═════════════════════════════════════════════════════════
    # 维度 1: 遗漏检查（纯代码）
    # ═════════════════════════════════════════════════════════
    missed = _check_coverage(edit_plan, frame_labels)

    # ═════════════════════════════════════════════════════════
    # 维度 2 & 3: LLM 质检（可选）
    # ═════════════════════════════════════════════════════════
    quality = _llm_quality_check(edit_plan, strategy, state)
    false_positives = quality.get("false_positives", [])
    boundary_issues = quality.get("boundary_issues", [])

    # ═════════════════════════════════════════════════════════
    # 判定
    # ═════════════════════════════════════════════════════════

    # 核心判定：击杀遗漏数
    real_missed = [m for m in missed if m.get("event") == "kill"]

    if is_last_round:
        # 最后一轮：除非明显漏击杀，否则通过
        if not real_missed:
            approved = True
            print(f"[📋 审核] 最后轮次无击杀遗漏 → ✅ 保底通过")
        else:
            approved = False
            print(f"[📋 审核] ⚠️ 最后轮次仍遗漏 {len(real_missed)} 个击杀")
    else:
        # 正常轮次：零遗漏 + 零误判 = 通过（boundary_issues 仅供参考，不导致拒绝）
        approved = len(real_missed) == 0 and len(false_positives) == 0

    # ── 汇总 issues ──
    issues = []
    for m in missed:
        issues.append(f"[遗漏] {m.get('time', '?')}s {m.get('event', '')}: {m.get('reason', '')}")
    for fp in false_positives:
        issues.append(f"[误判] 片段 {fp.get('segment_index', '?')}: {fp.get('reason', '')}")
    for b in boundary_issues:
        issues.append(f"[参考] 片段 {b.get('segment_index', '?')}: {b.get('reason', '')}")

    # ── 生成 fix_instructions（只含可操作项，boundary 不传入以免 Editor 误改）──
    fix_parts = []
    if missed:
        times = ", ".join(str(m["time"]) + "s" for m in missed)
        fix_parts.append(f"请确保以下时间点被覆盖: {times}")
    if false_positives:
        fix_parts.append("请移除或合并误判片段")
    fix_instructions = "; ".join(fix_parts) if fix_parts else ""

    print(f"[📋 审核] {'✅ 通过' if approved else '❌ 不通过'} "
          f"(遗漏={len(real_missed)}, 误判={len(false_positives)}, 边界={len(boundary_issues)})")

    return {
        "review_score": 100.0 if approved else 0.0,
        "review_issues": issues,
        "review_approved": approved,
        "plan_approved": approved,
        "review_suggestions": fix_instructions,
        "review_round": review_round,
    }
