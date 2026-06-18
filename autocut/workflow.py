"""LangGraph 工作流 — Agent 编排主流程.

工作流拓扑:
    START → director → analyzer → editor → reviewer
                                  ↑          │
                                  └─ retry ──┘ (不通过时回退，最多 N 轮)
                                        │
                                        ↓ (通过 / 超限)
                                       END

使用方式:
    from autocut.workflow import create_workflow

    wf = create_workflow()
    result = wf.invoke({
        "video_path": "/path/to/video.mp4",
        "user_requirement": "剪成3分钟精华版，竖屏9:16",
    })
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from autocut.state import VideoEditState
from autocut.config import settings, OUTPUT_DIR
from autocut.agents import director_node, analyzer_node, editor_node, reviewer_node


# ═══════════════════════════════════════════════════════════
# 条件路由
# ═══════════════════════════════════════════════════════════

def route_after_review(state: VideoEditState) -> str:
    """审核后的路由决策."""
    # 检查是否有错误
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"

    # 审核通过 → 结束
    if state.get("review_approved", False):
        print("[路由] 审核通过 ✅ → 结束")
        return "end"

    # 超过最大重试轮数 → 结束
    current_round = state.get("review_round", 0)
    if current_round >= settings.max_review_rounds:
        print(f"[路由] 已达最大重试轮数 ({settings.max_review_rounds}) → 强制结束")
        return "end"

    # 不通过且未超限 → 返回剪辑节点重试
    print(f"[路由] 审核不通过，返回剪辑节点重试 (第 {current_round} 轮)")
    return "retry"


# ═══════════════════════════════════════════════════════════
# 构建工作流
# ═══════════════════════════════════════════════════════════

def build_workflow() -> StateGraph:
    """构建 LangGraph 工作流图."""
    workflow = StateGraph(VideoEditState)

    # 添加节点
    workflow.add_node("director", director_node)
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("editor", editor_node)
    workflow.add_node("reviewer", reviewer_node)

    # 设置入口
    workflow.set_entry_point("director")

    # 连线: director → analyzer → editor → reviewer
    workflow.add_edge("director", "analyzer")
    workflow.add_edge("analyzer", "editor")
    workflow.add_edge("editor", "reviewer")

    # 条件边: reviewer → editor (retry) or END
    workflow.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "retry": "editor",
            "end": END,
        },
    )

    return workflow


def create_workflow():
    """创建编译好的工作流实例（可直接 invoke）."""
    return build_workflow().compile()


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def run_editing_task(
    video_path: str,
    user_requirement: str,
    output_dir: str = "",
    target_duration: float | None = None,
    target_aspect_ratio: str | None = None,
) -> dict:
    """一键运行完整的视频剪辑任务.

    Args:
        video_path: 原始视频文件路径
        user_requirement: 用户剪辑需求描述
        output_dir: 输出目录，默认使用全局配置
        target_duration: 目标时长（秒），可选
        target_aspect_ratio: 目标画幅，如 "9:16"、"16:9"，可选

    Returns:
        dict: 包含 final_output, review_score, review_issues 等字段的最终 State
    """
    from pathlib import Path

    out = output_dir or str(OUTPUT_DIR)
    Path(out).mkdir(parents=True, exist_ok=True)

    initial_state: VideoEditState = {
        "video_path": video_path,
        "user_requirement": user_requirement,
        "target_duration": target_duration,
        "target_aspect_ratio": target_aspect_ratio,
        "output_dir": out,
        "review_round": 0,
    }

    workflow = create_workflow()
    result = workflow.invoke(initial_state)

    return result
