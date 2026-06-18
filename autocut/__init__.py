"""AutoCut Agent — 基于 LangGraph 的智能视频剪辑 AI Agent 后端."""

import sys
import io

# Windows 下强制 UTF-8 输出，解决 emoji 乱码
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )

__version__ = "0.1.0"
