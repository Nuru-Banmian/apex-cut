"""LangGraph 工作流 — Agent 编排主流程.

工作流拓扑:
    START → director → route_after_director
                          ├── 缓存命中 → cache_loader → editor
                          └── 缓存未命中 → analyzer → editor → END

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
from apex_cut.agents import director_node, analyzer_node, editor_node
from apex_cut.agents.loader import cache_loader_node
from apex_cut.cache import has_cache


# ═══════════════════════════════════════════════════════════
# 条件路由
# ═══════════════════════════════════════════════════════════

def route_after_director(state: VideoEditState) -> str:
    """导演之后的路由：有缓存 → 跳过分析，无缓存 → 分析."""
    video_path = state.get("video_path", "")

    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"

    if video_path and has_cache(video_path,
                                frame_interval=state.get("frame_interval", 0) or 0,
                                max_vision_frames=state.get("max_vision_frames", 0) or 0,
                                roi_hash=state.get("roi_hash", "")):
        print("[路由]  缓存命中 → 跳过视频分析，直接加载")
        return "loader"

    print("[路由]  无缓存 → 启动视频分析")
    return "analyzer"


def route_after_loader(state: VideoEditState) -> str:
    """缓存加载后路由：成功 → Editor，失败 → Analyzer."""
    if state.get("_cache_miss"):
        print("[路由] ️ 缓存加载失败 → 回退到视频分析")
        return "analyzer"
    if state.get("error"):
        print("[路由] 检测到错误，终止流程")
        return "end"
    print("[路由]  缓存加载完成 → 进入剪辑")
    return "editor"


# ═══════════════════════════════════════════════════════════
# 构建工作流
# ═══════════════════════════════════════════════════════════

def build_workflow() -> StateGraph:
    """构建 LangGraph 工作流图."""
    workflow = StateGraph(VideoEditState)

    workflow.add_node("director", director_node)
    workflow.add_node("loader", cache_loader_node)
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("editor", editor_node)

    workflow.set_entry_point("director")

    workflow.add_conditional_edges(
        "director",
        route_after_director,
        {
            "loader": "loader",
            "analyzer": "analyzer",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "loader",
        route_after_loader,
        {
            "editor": "editor",
            "analyzer": "analyzer",
            "end": END,
        },
    )

    workflow.add_edge("analyzer", "editor")
    workflow.add_edge("editor", END)

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
        dict: 包含 final_output 等字段的最终 State
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
    }

    workflow = create_workflow()
    result = workflow.invoke(initial_state)

    return result
