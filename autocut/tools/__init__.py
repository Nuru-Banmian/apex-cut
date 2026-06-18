"""工具层 — 统一导出所有 Agent 工具."""

from autocut.tools.video_tools import VIDEO_TOOLS
from autocut.tools.audio_tools import AUDIO_TOOLS
from autocut.tools.subtitle_tools import SUBTITLE_TOOLS
from autocut.tools.vision_tools import VISION_TOOLS

# 所有可用工具
ALL_TOOLS = VIDEO_TOOLS + AUDIO_TOOLS + SUBTITLE_TOOLS + VISION_TOOLS

# 按 Agent 分配的工具集
DIRECTOR_TOOLS = []  # 导演主要负责规划和分发，不需要直接调用工具
ANALYZER_TOOLS = VIDEO_TOOLS[:1] + AUDIO_TOOLS + VISION_TOOLS  # probe + 音频分析 + 视觉分析
EDITOR_TOOLS = VIDEO_TOOLS + SUBTITLE_TOOLS  # 所有视频操作 + 字幕
REVIEWER_TOOLS = VIDEO_TOOLS[:1]  # 审核只需 probe 检查基本信息

__all__ = [
    "ALL_TOOLS",
    "DIRECTOR_TOOLS",
    "ANALYZER_TOOLS",
    "EDITOR_TOOLS",
    "REVIEWER_TOOLS",
]
