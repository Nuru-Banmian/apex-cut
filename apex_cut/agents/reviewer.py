"""审核 Agent — 当前已从工作流移除，保留文件占位.

后续 Planner 引入后可能恢复审核功能（LLM 自主审查自己的方案）。
"""

from __future__ import annotations

from apex_cut.state import VideoEditState


def reviewer_node(state: VideoEditState) -> dict:
    """审核节点 — 当前未启用."""
    return {}
