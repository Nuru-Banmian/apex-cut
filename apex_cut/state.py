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
    content_type: str                 # vlog/gaming/tutorial/interview/review/livestream/film/knowledge/life/auto
    target_duration: float | None
    target_aspect_ratio: str | None
    output_dir: str

    # ── 导演阶段产出 ──
    director_plan: dict               # 结构化剪辑策略
    director_plan_summary: str        # 策略摘要文本
    edit_style: str                   # 剪辑风格: 快节奏/正式/温情/...
    editing_notes: str                # 导演的剪辑要点（供下游参考）
    review_criteria: list[dict]       # 审核验收标准 [{check, pass_condition}]
    editing_constraints: dict         # 结构化剪辑约束 {hard:[], soft:[], rhythm, must_keep:[], must_remove:[]}
    # ★ 核心新增：可执行片段策略（Director 翻译用户意图 → Editor 机械执行）
    segment_strategy: dict            # {triggers, min_damage, padding_before, padding_after, merge_gap, min_segment, exclude_scenes, order, trim_strategy, priority_weights}

    # ── 运行时 API Key（前端传入，仅在内存中，不落盘） ──
    runtime_llm_provider: str     # deepseek / openai / qwen / anthropic / zhipu
    runtime_api_key: str          # 文本 LLM 的 API Key
    runtime_api_base: str         # Base URL（统一走 .env，前端不可配）
    runtime_vision_key: str       # 多模态视觉分析 Key
    runtime_vision_provider: str  # 视觉分析提供商
    runtime_text_model: str       # 文本模型名（前端选中）
    runtime_vision_model: str     # 视觉模型名（前端选中）

    # ── 高级设置（前端传入） ──
    frame_interval: float         # 抽帧间隔（0=自动）
    max_vision_frames: int        # 视觉分析帧数上限（0=不限制）
    max_review_rounds: int        # 审核最大轮数（前端自定义，默认6）

    # ── 对话历史（LangGraph 标准字段，Director Chat 使用独立参数传入） ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 分析阶段产出 ──
    frame_descriptions: list[dict] # [{frame, time_seconds, description}]  (deprecated: 被 frame_labels 取代)
    # ★ 分析阶段产出（只采集原始数据，不做决策）
    frame_labels: list[dict]       # [{frame, time_seconds, center_notification, player_stats, scene_type, _changes, _event}]
    # (deprecated) 以下字段保留兼容但不再使用
    segment_classifications: list[dict]
    # (deprecated) 以下字段保留兼容但不再使用
    highlights: list[dict]        # → 被 segment_classifications(action=keep) 取代
    quality_issues: list[dict]    # → 被 segment_classifications 取代
    content_summary: str          # → 不再需要
    content_tags: list[str]       # → 不再需要，固定 ["apex"]
    mood: str                     # → 不再需要
    mood_curve: list[dict]        # → 不再需要
    narrative_structure: dict     # 叙事结构（导演定骨架 → 分析器填具体时间）
    scene_analyses: list[dict]    # → 废弃

    # ── 剪辑阶段产出 ──
    edit_plan: list[dict]         # [{action, start, end, reason, transition}]
    subtitle_path: str            # 预留：字幕文件路径（未启用的功能）
    bgm_path: str                 # 预留：BGM 文件路径（未启用的功能）
    draft_output: str             # 当前阶段的中间输出视频

    # ── 审核阶段产出 ──
    review_score: float
    review_issues: list[str]
    review_approved: bool
    review_round: int
    review_suggestions: str
    plan_approved: bool              # Reviewer 批准剪辑方案 → Editor 才能执行裁剪

    # ── 最终产出 ──
    final_output: str
    final_subtitle: str           # 预留：最终字幕文件路径
    error: str                    # 异常信息
