"""LangGraph 工作流 — Agent 编排主流程.

工作流拓扑:
    START → director → route_after_director
                          ├── 缓存命中 → cache_loader → editor
                          └── 缓存未命中 → analyzer → editor
                                                      ↑          │
                                                      └──────────┘ (方案不通过→修改方案; 通过→裁剪)
                                                            │
                                                            ↓ (plan_approved)
                                                       editor (裁剪) → END

关键设计:
  - Director 输出 segment_strategy（精确可执行规则，不是软约束枚举）
  - Analyzer 只采集数据（frame_labels），不做决策
  - Editor 机械执行策略（纯代码，不依赖 LLM）
  - Reviewer 对照策略和需求审查方案
  - 侧挂缓存命中时跳过 Analyzer

使用方式:
    from apex_cut.workflow import create_workflow

    wf = create_workflow()
    result = wf.invoke({
        "video_path": "/path/to/video.mp4",
        "user_requirement": "剪成3分钟精华版，竖屏9:16",
    })
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from apex_cut.state import VideoEditState
from apex_cut.config import settings, OUTPUT_DIR
from apex_cut.agents import director_node, analyzer_node, editor_node, reviewer_node
from apex_cut.agents.loader import cache_loader_node
from apex_cut.cache import has_cache


# ═══════════════════════════════════════════════════════════
# 条件路由
# ═══════════════════════════════════════════════════════════

def route_after_director(state: VideoEditState) -> str:
    """导演之后的路由：有缓存 → 跳过分析，无缓存 → 分析."""
    video_path = state.get("video_path", "")

    # 检查是否有错误
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"

    # 侧挂缓存命中 → 跳过 Analyzer，直接加载缓存数据
    if video_path and has_cache(video_path,
                                frame_interval=state.get("frame_interval", 0) or 0,
                                max_vision_frames=state.get("max_vision_frames", 0) or 0):
        print("[路由]  缓存命中 → 跳过视频分析，直接加载")
        return "loader"

    print("[路由]  无缓存 → 启动视频分析")
    return "analyzer"


def route_after_loader(state: VideoEditState) -> str:
    """缓存加载后路由：成功 → Editor，失败(_cache_miss) → Analyzer."""
    if state.get("_cache_miss"):
        print("[路由] ️ 缓存加载失败 → 回退到视频分析")
        return "analyzer"
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"
    print("[路由]  缓存加载完成 → 进入剪辑")
    return "editor"


def route_after_editor(state: VideoEditState) -> str:
    """Editor 之后的路由决策."""
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"

    # 方案已批准 → Editor 刚完成裁剪 → 结束
    if state.get("plan_approved"):
        print("[路由] 裁剪完成  → 结束")
        return "end"

    # 方案未批准 → 刚生成/修改了方案 → 交给 Reviewer 审查
    print("[路由] 方案已生成 → 提交 Reviewer 审查")
    return "reviewer"


def route_after_review(state: VideoEditState) -> str:
    """Reviewer 之后的路由决策."""
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"

    # 方案通过 → Editor 执行裁剪
    if state.get("plan_approved"):
        print("[路由] 方案审查通过  → Editor 执行裁剪")
        return "editor"

    # 超过最大重试轮数 → 强制裁剪
    current_round = state.get("review_round", 0)
    max_rounds = state.get("max_review_rounds") or settings.max_review_rounds
    if current_round >= max_rounds:
        print(f"[路由] 已达最大重试轮数 ({max_rounds}) → 强制裁剪")
        return "editor"

    # 不通过且未超限 → 返回 Editor 修改方案
    print(f"[路由] 方案不通过，返回 Editor 修改 (第 {current_round} 轮)")
    return "editor"


# ═══════════════════════════════════════════════════════════
# 构建工作流
# ═══════════════════════════════════════════════════════════

def build_workflow() -> StateGraph:
    """构建 LangGraph 工作流图."""
    workflow = StateGraph(VideoEditState)

    # 添加节点
    workflow.add_node("director", director_node)
    workflow.add_node("loader", cache_loader_node)
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("editor", editor_node)
    workflow.add_node("reviewer", reviewer_node)

    # 设置入口
    workflow.set_entry_point("director")

    # Director 之后分叉：有缓存跳过分析，无缓存启动分析
    workflow.add_conditional_edges(
        "director",
        route_after_director,
        {
            "loader": "loader",
            "analyzer": "analyzer",
            "end": END,
        },
    )

    # Loader → Editor（或回退到 Analyzer）
    workflow.add_conditional_edges(
        "loader",
        route_after_loader,
        {
            "editor": "editor",
            "analyzer": "analyzer",
            "end": END,
        },
    )

    # Analyzer → Editor
    workflow.add_edge("analyzer", "editor")

    # Editor 之后分叉：方案模式 → reviewer / 裁剪模式 → END
    workflow.add_conditional_edges(
        "editor",
        route_after_editor,
        {
            "reviewer": "reviewer",
            "end": END,
        },
    )

    # Reviewer 之后：条件路由 → editor (裁剪/修改) or END (出错)
    workflow.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "editor": "editor",
            "end": END,
        },
    )

    return workflow


_compiled_workflow = None


def create_workflow():
    """创建编译好的工作流实例（可直接 invoke，编译结果缓存）."""
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = build_workflow().compile()
    return _compiled_workflow


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
