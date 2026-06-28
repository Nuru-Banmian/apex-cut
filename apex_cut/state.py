"""LangGraph 共享 State 定义.

所有 Agent 节点通过此 State 通信 — 每个节点读取上游字段、写入下游字段.
"""

from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class VideoEditState(TypedDict, total=False):
    """视频剪辑项目的全局 State.

    total=False 意味着所有字段可选，随着流程推进逐步填充.
    """

    # ── 用户输入 ──
    video_path: str
    user_requirement: str
    output_name: str                   # 自定义输出文件名（不含扩展名）
    content_type: str                  # vlog/gaming/tutorial/interview/review/livestream/film/knowledge/life/auto
    target_duration: float | None
    target_aspect_ratio: str | None
    output_dir: str

    # ── 导演阶段产出 ──
    edit_style: str                    # 剪辑风格: 快节奏/正式/温情/...
    editing_notes: str                 # 导演的剪辑要点

    # ── 运行时 API Key（前端传入，仅在内存中，不落盘）──
    runtime_llm_provider: str          # deepseek / openai / qwen / anthropic / zhipu
    runtime_api_key: str               # 文本 LLM 的 API Key
    runtime_api_base: str              # Base URL
    runtime_vision_key: str            # 多模态视觉分析 Key
    runtime_vision_provider: str       # 视觉分析提供商
    runtime_text_model: str            # 文本模型名
    runtime_vision_model: str          # 视觉模型名

    # ── 高级设置（前端传入）──
    frame_interval: float              # 抽帧间隔（0=自动）
    max_vision_frames: int             # 视觉分析帧数上限（0=不限制）

    # ── 对话历史 ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── ROI 配置（用户自定义）──
    roi_config: list[dict]             # [{type_id, rect: {x,y,w,h}, label, custom_instruction}]
    roi_hash: str                      # ROI 配置指纹

    # ── 分析阶段产出 ──
    # [{frame, time_seconds, has_combat, event, confidence, note, numbers: {kills, assists, damage}}]
    frame_labels: list[dict]

    # ── 剪辑阶段产出 ──
    edit_plan: list[dict]              # [{start, end, reason, score, events}]

    # ── 最终产出 ──
    final_output: str
    manifest_path: str
    error: str
