"""审核 Agent — 质量检查，决定是否通过."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from autocut.state import VideoEditState
from autocut.config import create_llm, _extract_runtime_keys, settings
from autocut.errors import check_and_raise


REVIEWER_SYSTEM_PROMPT = """你是一位严格的视频质量审核员。你需要审核 AI 剪辑的成品，给出评分和改进建议。

审核维度（每项 0-25 分，总分 100）：
1. **时长控制** (25分)：成品时长是否接近目标时长（误差 ±10% 内满分）
2. **内容完整性** (25分)：核心信息是否保留，是否有内容断裂
3. **节奏流畅度** (25分)：转场是否自然，节奏是否合理
4. **技术质量** (25分)：字幕同步、画面质量、音量一致性

请以 JSON 格式返回审核结果：

{
    "score_duration": 0-25,
    "score_content": 0-25,
    "score_rhythm": 0-25,
    "score_technical": 0-25,
    "total_score": 汇总分数,
    "approved": true/false,
    "issues": ["问题1", "问题2"],
    "suggestions": "具体的改进建议（给剪辑 Agent 的反馈）",
    "summary": "审核总结（1-2句话）"
}

通过标准：总分 >= 70 且没有严重问题。
只返回 JSON。"""


def reviewer_node(state: VideoEditState) -> dict:
    """审核节点 — 质量检查."""
    review_round = state.get("review_round", 0)
    requirement = state.get("user_requirement", "")
    target_duration = state.get("target_duration")
    draft_output = state.get("draft_output", "")
    edit_plan = state.get("edit_plan", [])
    content_summary = state.get("content_summary", "")

    print(f"\n[📋 审核] 第 {review_round} 轮审核")

    # 构建审查上下文
    context = f"""## 用户需求
{requirement}

## 目标时长
{target_duration or '未指定'}

## 内容摘要
{content_summary or '无'}

## 剪辑方案
{json.dumps(edit_plan, ensure_ascii=False)[:3000]}

## 当前轮次
第 {review_round} 轮（最大 {settings.max_review_rounds} 轮）
"""

    try:
        provider, api_key, api_base = _extract_runtime_keys(state)
        llm = create_llm(temperature=0.2, runtime_provider=provider,
                         runtime_api_key=api_key, runtime_base_url=api_base)
        response = llm.invoke([
            SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        review = json.loads(content)

        total_score = review.get("total_score", 0)
        approved = review.get("approved", False)

        print(f"[📋 审核] 评分: {total_score}/100 | {'✅ 通过' if approved else '❌ 不通过'}")
        if review.get("issues"):
            for issue in review["issues"]:
                print(f"  - 问题: {issue}")

        return {
            "review_score": total_score,
            "review_issues": review.get("issues", []),
            "review_approved": approved,
            "review_suggestions": review.get("suggestions", ""),
            "review_round": review_round,
        }
    except json.JSONDecodeError as e:
        print(f"[📋 审核] JSON 解析失败: {e}")
        return {
            "review_score": 60.0,
            "review_issues": ["审核结果解析失败，自动通过"],
            "review_approved": True,
            "review_suggestions": "LLM 返回格式异常，请检查剪辑方案的 JSON 结构",
            "review_round": review_round,
        }
    except Exception as e:
        check_and_raise(e, "审核")
        print(f"[📋 审核] LLM 调用异常: {e}")
        return {
            "review_score": 60.0,
            "review_issues": [f"审核服务暂不可用: {str(e)[:100]}"],
            "review_approved": True,
            "review_suggestions": "审核 Agent 异常，已自动通过（请人工检查成品）",
            "review_round": review_round,
        }
