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
    target_duration: float | None
    target_aspect_ratio: str | None
    output_dir: str

    # ── 导演阶段产出 ──
    director_plan: dict               # 结构化剪辑策略
    director_plan_summary: str        # 策略摘要文本
    edit_style: str                   # 剪辑风格: 快节奏/正式/温情/...

    # ── 运行时 API Key（前端传入，仅在内存中，不落盘） ──
    runtime_llm_provider: str     # deepseek / openai / anthropic
    runtime_api_key: str          # 主 LLM 的 API Key
    runtime_api_base: str         # Base URL（统一走 .env，前端不可配）
    runtime_vision_key: str       # 多模态视觉分析 Key
    runtime_vision_provider: str  # 视觉分析提供商: openai / zhipu / qwen

    # ── 对话历史（LangGraph 标准字段） ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 分析阶段产出 ──
    # 音频维度
    transcript: list[dict]        # [{start, end, text, speaker, confidence}]
    silences: list[dict]          # [{start, end, duration}]
    audio_energy: list[float]     # 每秒 RMS 能量值
    energy_peaks: list[dict]      # [{time, energy}] 高能时刻
    # 画面维度
    scenes: list[dict]            # [{start, end, scene_number}]
    frame_descriptions: list[dict] # [{frame, time_seconds, description}]
    # 融合分析
    highlights: list[dict]        # [{start, end, score, reason}] 精彩片段
    quality_issues: list[dict]    # [{start, end, issue_type, severity, detail}]
    content_summary: str          # 视频内容摘要
    content_tags: list[str]       # 内容标签: 教程/访谈/Vlog/...
    mood: str                     # 整体情绪
    mood_curve: list[dict]        # [{time, mood, confidence}] 情绪变化曲线
    narrative_structure: dict     # {intro, body, climax, outro} 叙事结构
    scene_analyses: list[dict]    # [{scene, start, end, visual, audio, summary}]

    # ── 剪辑阶段产出 ──
    edit_plan: list[dict]         # [{action, start, end, reason, transition}]
    subtitle_path: str
    bgm_path: str
    draft_output: str             # 当前阶段的中间输出视频

    # ── 审核阶段产出 ──
    review_score: float
    review_issues: list[str]
    review_approved: bool
    review_round: int
    review_suggestions: str

    # ── 最终产出 ──
    final_output: str
    final_subtitle: str
    error: str                    # 异常信息
