"""全局配置 — 支持环境变量覆盖."""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _find_ffmpeg() -> str:
    """自动查找 ffmpeg 可执行文件路径."""
    env_path = os.getenv("FFMPEG_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    return "ffmpeg"


def _find_ffprobe() -> str:
    """自动查找 ffprobe 可执行文件路径."""
    env_path = os.getenv("FFPROBE_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe
    try:
        import imageio_ffmpeg
        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
        binaries_dir = ffmpeg_path.parent
        for f in binaries_dir.glob("ffprobe*"):
            return str(f)
    except (ImportError, Exception):
        pass
    return "ffprobe"


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
except ImportError:
    pass  # python-dotenv 未安装时静默跳过

# 各目录
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
MODEL_DIR = PROJECT_ROOT / "models"

for d in [DATA_DIR, OUTPUT_DIR, MODEL_DIR]:
    d.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    # ── LLM 提供商: deepseek / openai / anthropic ──
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "deepseek")
    )

    # DeepSeek
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    deepseek_model: str = "deepseek-chat"         # 文本理解/剪辑决策
    deepseek_base_url: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )

    # ── 视觉分析提供商: openai / zhipu / qwen ──
    vision_provider: str = field(
        default_factory=lambda: os.getenv("VISION_PROVIDER", "openai")
    )

    # OpenAI（多模态视觉分析 / 备用）
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    openai_model: str = "gpt-4o"
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )

    # 智谱AI GLM-4V（国产推荐，OpenAI 兼容）
    zhipu_api_key: str = field(
        default_factory=lambda: os.getenv("ZHIPU_API_KEY", "")
    )
    zhipu_model: str = "glm-4v-plus"
    zhipu_base_url: str = field(
        default_factory=lambda: os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    )

    # 阿里百炼 Qwen（文本+视觉通用 Key，qwen3.7-plus 原生多模态）
    qwen_api_key: str = field(
        default_factory=lambda: os.getenv("QWEN_API_KEY", "")
    )
    qwen_text_model: str = "qwen3.7-plus"       # 文本理解/剪辑决策（推荐 qwen3.7-plus / qwen3.7-max）
    qwen_model: str = "qwen3.7-plus"            # 多模态视觉分析（qwen3.7-plus 原生支持图文，与文本用同一模型）
    qwen_base_url: str = field(
        default_factory=lambda: os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )

    # Anthropic（可选用）
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = "claude-sonnet-4-6"

    # ── Whisper ──
    whisper_model: str = "medium"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # ── FFmpeg ──
    ffmpeg_path: str = field(default_factory=_find_ffmpeg)
    ffprobe_path: str = field(default_factory=_find_ffprobe)
    output_format: str = "mp4"
    output_codec: str = "libx264"
    output_crf: int = 23

    # ── 剪辑参数 ──
    max_review_rounds: int = 3
    min_segment_duration: float = 0.5
    max_silence_duration: float = 2.0
    default_aspect_ratio: str = "16:9"

    # ── 字幕 ──
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 48


settings = Settings()


# ═══════════════════════════════════════════════════════════
# 线程级运行时 Key（前端传入，不落盘，仅当前任务可见）
# ═══════════════════════════════════════════════════════════

import threading

_runtime = threading.local()


def set_runtime_keys(*, vision_key: str = "", vision_provider: str = ""):
    """设置当前线程的运行时视觉配置（API 路由在启动任务前调用）."""
    _runtime.vision_key = vision_key
    _runtime.vision_provider = vision_provider


def _get_runtime_vision_key() -> str:
    """获取当前线程的视觉分析 Key."""
    return getattr(_runtime, "vision_key", "")


def _get_runtime_vision_provider() -> str:
    """获取当前线程的视觉分析提供商."""
    return getattr(_runtime, "vision_provider", "")


# ═══════════════════════════════════════════════════════════
# 统一 LLM 工厂函数
# ═══════════════════════════════════════════════════════════

def _extract_runtime_keys(state: dict) -> tuple[str, str, str]:
    """从 State 中提取运行时 API Key 配置.

    Base URL 优先使用前端传入的运行时值，否则从 .env 配置中获取.
    """
    provider = state.get("runtime_llm_provider", "") or settings.llm_provider
    api_key = state.get("runtime_api_key", "") or ""
    api_base = state.get("runtime_api_base", "") or ""
    # runtime_api_base 为空时，根据 provider 从 settings 获取默认 base_url
    if not api_base:
        if provider == "deepseek":
            api_base = settings.deepseek_base_url
        elif provider == "qwen":
            api_base = settings.qwen_base_url
        elif provider == "openai":
            api_base = settings.openai_base_url
    return (provider, api_key, api_base)


def create_llm(temperature: float = 0.3, bind_tools: Optional[list] = None,
              runtime_provider: str = "", runtime_api_key: str = "",
              runtime_base_url: str = ""):
    """根据配置创建 LLM 实例.

    runtime_* 参数从 State 传入（用户在前端填的 Key），优先级高于 .env.
    所有 Agent 节点通过此函数获取 LLM，保证切换提供商只需改 .env 一行.
    """
    provider = runtime_provider or settings.llm_provider

    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek
        llm = ChatDeepSeek(
            model=settings.deepseek_model,
            api_key=runtime_api_key or settings.deepseek_api_key,
            api_base=runtime_base_url or settings.deepseek_base_url,
            temperature=temperature,
        )

    elif provider == "qwen":
        # 千问使用 OpenAI 兼容 API，一个 Key 同时支持文本和视觉
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=settings.qwen_text_model,
            api_key=runtime_api_key or settings.qwen_api_key,
            base_url=runtime_base_url or settings.qwen_base_url,
            temperature=temperature,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=settings.anthropic_model,
            api_key=runtime_api_key or settings.anthropic_api_key,
            temperature=temperature,
        )

    else:  # openai
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=runtime_api_key or settings.openai_api_key,
            base_url=runtime_base_url or settings.openai_base_url,
            temperature=temperature,
        )

    if bind_tools:
        llm = llm.bind_tools(bind_tools)

    return llm


def create_multimodal_llm(temperature: float = 0.3,
                          runtime_api_key: str = "",
                          runtime_base_url: str = "",
                          runtime_provider: str = ""):
    """创建支持多模态（视觉）的 LLM 实例.

    支持提供商:
      - openai:  OpenAI GPT-4o（默认）
      - zhipu:   智谱AI GLM-4V-Plus（国产推荐，OpenAI 兼容）
      - qwen:    阿里百炼 Qwen-VL-Max（国产备选，OpenAI 兼容）

    zhipu 和 qwen 的 API 完全兼容 OpenAI 格式，只需换 url + key + model.
    """
    from langchain_openai import ChatOpenAI

    provider = runtime_provider or settings.vision_provider

    if provider == "zhipu":
        model = settings.zhipu_model
        api_key = runtime_api_key or settings.zhipu_api_key
        base_url = runtime_base_url or settings.zhipu_base_url
        print(f"  👁️  视觉 LLM: 智谱AI {model}")

    elif provider == "qwen":
        model = settings.qwen_model
        api_key = runtime_api_key or settings.qwen_api_key
        base_url = runtime_base_url or settings.qwen_base_url
        print(f"  👁️  视觉 LLM: 阿里百炼 {model}")

    else:  # openai (default)
        model = settings.openai_model
        api_key = runtime_api_key or settings.openai_api_key
        base_url = runtime_base_url or settings.openai_base_url
        print(f"  👁️  视觉 LLM: OpenAI {model}")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
    )


# ═══════════════════════════════════════════════════════════
# .env 配置持久化
# ═══════════════════════════════════════════════════════════

def _mask_key(key: str) -> str:
    """遮盖 Key，只显示最后4位."""
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]


def get_config_summary() -> dict:
    """获取当前配置摘要（Key 已遮盖）供前端展示."""
    return {
        "llm_provider": settings.llm_provider,
        "deepseek_api_key": _mask_key(settings.deepseek_api_key),
        "deepseek_model": settings.deepseek_model,
        "openai_api_key": _mask_key(settings.openai_api_key),
        "openai_model": settings.openai_model,
        "vision_provider": settings.vision_provider,
        "zhipu_api_key": _mask_key(settings.zhipu_api_key),
        "qwen_api_key": _mask_key(settings.qwen_api_key),
        "anthropic_api_key": _mask_key(settings.anthropic_api_key),
    }


def save_config_to_env(config: dict) -> bool:
    """保存 API 配置到 .env 文件.

    只保存用户显式填写的字段（非空值），
    已存在的 .env 中其他行保持不变.
    """
    # 字段名 → .env key 映射
    FIELD_TO_ENV = {
        "llm_provider": "LLM_PROVIDER",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "deepseek_model": "DEEPSEEK_MODEL",
        "openai_api_key": "OPENAI_API_KEY",
        "openai_model": "OPENAI_MODEL",
        "vision_provider": "VISION_PROVIDER",
        "zhipu_api_key": "ZHIPU_API_KEY",
        "qwen_api_key": "QWEN_API_KEY",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
    }

    # 收集要写入的 key=value（只保存非空值）
    updates = {}
    for field, env_key in FIELD_TO_ENV.items():
        val = config.get(field, "")
        if val:  # 只保存有值的
            updates[env_key] = val

    if not updates:
        return False

    # 读取现存的 .env（保留注释和未涉及的配置）
    existing_lines = []
    updated_keys = set()
    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        # 更新已有的行
        for i, line in enumerate(existing_lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        existing_lines[i] = f"{key}={updates[key]}"
                        updated_keys.add(key)

    # 追加新的 key（文件中不存在的）
    for env_key, val in updates.items():
        if env_key not in updated_keys:
            existing_lines.append(f"{env_key}={val}")

    try:
        ENV_FILE.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
        # 更新内存中的 settings 对象（下次 LLM 创建时生效）
        _apply_config_to_settings(updates)
        return True
    except Exception as e:
        print(f"保存 .env 失败: {e}")
        return False


def _apply_config_to_settings(env_updates: dict):
    """将 .env 的 key=value 应用到内存中的 settings 对象."""
    key_to_attr = {
        "LLM_PROVIDER": "llm_provider",
        "DEEPSEEK_API_KEY": "deepseek_api_key",
        "DEEPSEEK_MODEL": "deepseek_model",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "VISION_PROVIDER": "vision_provider",
        "ZHIPU_API_KEY": "zhipu_api_key",
        "QWEN_API_KEY": "qwen_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
    }
    for env_key, val in env_updates.items():
        attr = key_to_attr.get(env_key)
        if attr and hasattr(settings, attr):
            setattr(settings, attr, val)
    # 同时更新 os.environ，确保新进程可见
    for env_key, val in env_updates.items():
        os.environ[env_key] = val
