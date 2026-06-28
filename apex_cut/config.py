"""全局配置 — 支持环境变量覆盖."""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _find_ffmpeg() -> str:
    """自动查找 ffmpeg 可执行文件路径（优先完整版，含 GPU 编码器）."""
    env_path = os.getenv("FFMPEG_PATH", "")
    if env_path and Path(env_path).exists():
        return env_path

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        # 检查是否支持 NVENC（完整版）
        import subprocess as _sp
        try:
            r = _sp.run([system_ffmpeg, "-hide_banner", "-encoders"],
                       capture_output=True, text=True, timeout=5)
            if "h264_nvenc" in r.stdout or "h264_qsv" in r.stdout:
                return system_ffmpeg
        except Exception:
            pass
        # 不支持 GPU 但可用，先记下
        _cpu_ffmpeg = system_ffmpeg
    else:
        _cpu_ffmpeg = None

    # 尝试常见完整版 ffmpeg 路径
    candidates = [
        "ffmpeg",  # 某些用户把完整版放在 PATH 里叫 ffmpeg
        os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\ffmpeg\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                r = _sp.run([c, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=5)
                if "h264_nvenc" in r.stdout or "h264_qsv" in r.stdout:
                    return c
            except Exception:
                pass

    # 回退：PATH 中的 ffmpeg（无 GPU）或 imageio_ffmpeg
    if _cpu_ffmpeg:
        return _cpu_ffmpeg
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


def _default_subtitle_font() -> str:
    """根据操作系统返回默认中文字体."""
    import platform
    system = platform.system()
    if system == "Windows":
        return os.getenv("SUBTITLE_FONT", "Microsoft YaHei")
    elif system == "Darwin":
        return os.getenv("SUBTITLE_FONT", "PingFang SC")
    else:
        return os.getenv("SUBTITLE_FONT", "Noto Sans CJK SC")


def _detect_hwaccel() -> str:
    """自动检测可用的硬件加速方案.

    优先使用 FFMPEG_HWACCEL 环境变量，否则自动探测.
    返回: "cuda" | "qsv" | "amf" | "none"
    """
    # 手动指定优先
    env_val = os.getenv("FFMPEG_HWACCEL", "")
    if env_val and env_val != "auto":
        return env_val

    import subprocess
    import shutil
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        encoders = result.stdout
        if "h264_nvenc" in encoders:
            return "cuda"
        if "h264_qsv" in encoders:
            return "qsv"
        if "h264_amf" in encoders:
            return "amf"
    except Exception:
        pass

    return "none"


def _detect_best_codec() -> str:
    """根据硬件加速方案选择最优编码器."""
    hw = os.getenv("FFMPEG_HWACCEL", "") or _detect_hwaccel()
    codec_map = {"cuda": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}
    return codec_map.get(hw, "libx264")


def get_gpu_info() -> dict:
    """全面检测 GPU 能力，返回可供前端展示的信息.

    检测项目:
      - FFmpeg 硬件编码器 (NVENC/QSV/AMF)
      - FFmpeg 硬件解码器
    """
    import subprocess
    ffmpeg = settings.ffmpeg_path
    info = {
        "ffmpeg_encode": "none",
        "ffmpeg_decode": "none",
        "summary": "CPU 模式",
    }

    # 1) FFmpeg 编码器
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        encoders = result.stdout
        if "h264_nvenc" in encoders:
            info["ffmpeg_encode"] = "nvenc"
        elif "h264_qsv" in encoders:
            info["ffmpeg_encode"] = "qsv"
        elif "h264_amf" in encoders:
            info["ffmpeg_encode"] = "amf"
    except Exception:
        pass

    # 2) FFmpeg 解码器
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-decoders"],
            capture_output=True, text=True, timeout=10,
        )
        decoders = result.stdout
        if "h264_cuvid" in decoders:
            info["ffmpeg_decode"] = "cuvid"
        elif "h264_qsv" in decoders:
            info["ffmpeg_decode"] = "qsv"
    except Exception:
        pass

    # 生成摘要
    parts = []
    if info["ffmpeg_encode"] != "none":
        parts.append(f"编码: {info['ffmpeg_encode']}")
    if info["ffmpeg_decode"] != "none":
        parts.append(f"解码: {info['ffmpeg_decode']}")
    info["summary"] = " | ".join(parts) if parts else "CPU 模式"

    print(f"[GPU 检测] ffmpeg: {ffmpeg}  编码器: {info['ffmpeg_encode']}  解码器: {info['ffmpeg_decode']}")
    return info


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
except ImportError:
    import warnings
    warnings.warn("python-dotenv 未安装，.env 文件不会被加载，所有 API Key 将为空。请运行: pip install python-dotenv")

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
    deepseek_model: str = "deepseek-v4-pro"       # 文本理解/剪辑决策
    deepseek_base_url: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )

    # ── 视觉分析提供商: zhipu / qwen / openai ──
    vision_provider: str = field(
        default_factory=lambda: os.getenv("VISION_PROVIDER", "zhipu")
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

    # 阿里百炼 Qwen（文本+视觉通用 Key，OpenAI 兼容 API）
    # 文本模型: 导演/剪辑/审核 → 需要强推理能力
    # 视觉模型: 画面分析描述 → 需要原生多模态
    # 所有模型均支持 文本+图片+视频 输入
    qwen_api_key: str = field(
        default_factory=lambda: os.getenv("QWEN_API_KEY", "")
    )
    qwen_text_model: str = field(
        default_factory=lambda: os.getenv("QWEN_TEXT_MODEL", "qwen3.7-plus")
    )
    #   ┌─ 质量优先 ─────────────────────────────────────────────┐
    #   │ qwen3.7-max-2026-06-08  顶级推理，最贵，复杂任务首选   │
    #   │ qwen3.7-plus            旗舰平衡，1M 上下文 (推荐)    │
    #   │ qwen3.6-plus            上代旗舰，1M 上下文              │
    #   │ qwen3.5-plus            高性价比，1M 上下文              │
    #   ├─ 速度优先 ─────────────────────────────────────────────┤
    #   │ qwen3.6-flash           快速响应，1M 上下文              │
    #   │ qwen3.5-flash           轻量快速，1M 上下文 (省钱)       │
    #   └────────────────────────────────────────────────────────┘
    qwen_vision_model: str = field(
        default_factory=lambda: os.getenv("QWEN_VISION_MODEL", "qwen3-vl-flash")
    )
    #   ┌─ 质量优先 ─────────────────────────────────────────────┐
    #   │ qwen3.7-plus            原生多模态，1M 上下文 (推荐)   │
    #   │ qwen3.6-plus            原生多模态，1M 上下文            │
    #   │ qwen3-vl-plus           专用视觉模型，262K 上下文        │
    #   ├─ 速度优先 ─────────────────────────────────────────────┤
    #   │ qwen3.6-flash           快速视觉，1M 上下文              │
    #   │ qwen3-vl-flash          轻量视觉，262K 上下文 (省钱)     │
    #   └────────────────────────────────────────────────────────┘
    qwen_base_url: str = field(
        default_factory=lambda: os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )

    # Anthropic（可选用）
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )

    # ── FFmpeg ──
    ffmpeg_path: str = field(default_factory=_find_ffmpeg)
    ffprobe_path: str = field(default_factory=_find_ffprobe)
    output_format: str = "mp4"
    output_codec: str = field(
        default_factory=lambda: _detect_best_codec()
    )
    output_crf: int = 23  # CRF 仅用于软件编码；GPU 编码自动切换为 QP/CQ
    ffmpeg_hwaccel: str = field(
        default_factory=lambda: _detect_hwaccel()
    )

    # ── 剪辑参数 ──
    max_silence_duration: float = 2.0
    default_aspect_ratio: str = "16:9"

    # ── 视觉分析 ──
    vision_max_px: int = field(
        default_factory=lambda: int(os.getenv("VISION_MAX_PX", "600"))
    )  # 发给视觉 LLM 的图片长边最大像素。400-600 是精度/速度最佳平衡

    # ── 字幕 ──
    subtitle_font: str = field(
        default_factory=lambda: os.getenv("SUBTITLE_FONT", _default_subtitle_font())
    )
    subtitle_font_size: int = 48


# Audio/Whisper removed — Apex Legends doesn't need speech analysis

settings = Settings()

# 惰性 GPU 检测 — 避免 import 时阻塞（--version 也会触发）
_gpu_info_cache: dict | None = None


def get_gpu_info_cached() -> dict:
    """获取 GPU 检测结果（惰性加载，首次调用时才检测）."""
    global _gpu_info_cache
    if _gpu_info_cache is None:
        _gpu_info_cache = get_gpu_info()
    return _gpu_info_cache


# ═══════════════════════════════════════════════════════════
# 线程级运行时 Key（前端传入，不落盘，仅当前任务可见）
# ═══════════════════════════════════════════════════════════

import threading

_runtime = threading.local()


def set_runtime_keys(*, vision_key: str = "", vision_provider: str = "", vision_model: str = ""):
    """设置当前线程的运行时视觉配置（API 路由在启动任务前调用）."""
    _runtime.vision_key = vision_key
    _runtime.vision_provider = vision_provider
    _runtime.vision_model = vision_model


def _get_runtime_vision_key() -> str:
    """获取当前线程的视觉分析 Key."""
    return getattr(_runtime, "vision_key", "")


def _get_runtime_vision_provider() -> str:
    """获取当前线程的视觉分析提供商."""
    return getattr(_runtime, "vision_provider", "")


def _get_runtime_vision_model() -> str:
    """获取当前线程的视觉分析模型名."""
    return getattr(_runtime, "vision_model", "")


# ═══════════════════════════════════════════════════════════
# 统一 LLM 工厂函数
# ═══════════════════════════════════════════════════════════

def _extract_runtime_keys(state: dict) -> tuple[str, str, str, str]:
    """从 State 中提取运行时 API Key + Model 配置.

    返回: (provider, api_key, api_base, model)
    Base URL 优先使用前端传入的运行时值，否则从 .env 配置中获取.
    """
    provider = state.get("runtime_llm_provider", "") or settings.llm_provider
    api_key = state.get("runtime_api_key", "") or ""
    api_base = state.get("runtime_api_base", "") or ""
    model = state.get("runtime_text_model", "")
    # runtime_api_base 为空时，根据 provider 从 settings 获取默认 base_url
    if not api_base:
        if provider == "deepseek":
            api_base = settings.deepseek_base_url
        elif provider == "qwen":
            api_base = settings.qwen_base_url
        elif provider == "zhipu":
            api_base = settings.zhipu_base_url
        elif provider == "openai":
            api_base = settings.openai_base_url
    return (provider, api_key, api_base, model)


def create_llm(temperature: float = 0.3, bind_tools: Optional[list] = None,
              runtime_provider: str = "", runtime_api_key: str = "",
              runtime_base_url: str = "", runtime_model: str = ""):
    """根据配置创建 LLM 实例.

    runtime_* 参数从 State 传入（用户在前端填的 Key），优先级高于 .env.
    runtime_model: 前端选中的模型名，优先级高于 settings 默认值.
    所有 Agent 节点通过此函数获取 LLM，保证切换提供商只需改 .env 一行.
    """
    provider = runtime_provider or settings.llm_provider

    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek
        model = runtime_model or settings.deepseek_model
        llm = ChatDeepSeek(
            model=model,
            api_key=runtime_api_key or settings.deepseek_api_key,
            api_base=runtime_base_url or settings.deepseek_base_url,
            temperature=temperature,
        )

    elif provider in ("qwen", "zhipu"):
        # 千问 / 智谱 均使用 OpenAI 兼容 API
        from langchain_openai import ChatOpenAI
        if provider == "qwen":
            model = runtime_model or settings.qwen_text_model
            key = runtime_api_key or settings.qwen_api_key
            base = runtime_base_url or settings.qwen_base_url
        else:  # zhipu
            model = runtime_model or "GLM-4.7-Flash"
            key = runtime_api_key or settings.zhipu_api_key
            base = runtime_base_url or settings.zhipu_base_url
        llm = ChatOpenAI(
            model=model, api_key=key, base_url=base, temperature=temperature,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = runtime_model or settings.anthropic_model
        llm = ChatAnthropic(
            model=model,
            api_key=runtime_api_key or settings.anthropic_api_key,
            temperature=temperature,
        )

    else:  # openai (default)
        from langchain_openai import ChatOpenAI
        model = runtime_model or settings.openai_model
        llm = ChatOpenAI(
            model=model,
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
                          runtime_provider: str = "",
                          runtime_model: str = ""):
    """创建支持多模态（视觉）的 LLM 实例.

    支持提供商:
      - zhipu:   智谱AI GLM 系列（OpenAI 兼容）
      - qwen:    阿里百炼 Qwen-VL 系列（OpenAI 兼容）
      - openai:  OpenAI GPT-4o/4.1 系列
      - anthropic: Claude 系列（需通过 langchain_anthropic）

    zhipu / qwen / openai 的视觉 API 完全兼容 OpenAI 格式.
    runtime_model: 前端选中的视觉模型名，优先级高于 settings 默认值.
    """
    from langchain_openai import ChatOpenAI

    provider = runtime_provider or settings.vision_provider

    if provider == "zhipu":
        model = runtime_model or settings.zhipu_model
        api_key = runtime_api_key or settings.zhipu_api_key
        base_url = runtime_base_url or settings.zhipu_base_url
        print(f"  ️  视觉 LLM: 智谱AI {model}")

    elif provider == "qwen":
        model = runtime_model or settings.qwen_vision_model
        api_key = runtime_api_key or settings.qwen_api_key
        base_url = runtime_base_url or settings.qwen_base_url
        print(f"  ️  视觉 LLM: 阿里百炼 {model}")

    elif provider == "anthropic":
        # Anthropic Claude 原生支持视觉，但走自己的 SDK
        from langchain_anthropic import ChatAnthropic
        model = runtime_model or settings.anthropic_model
        api_key = runtime_api_key or settings.anthropic_api_key
        print(f"  ️  视觉 LLM: Anthropic {model}")
        return ChatAnthropic(
            model=model, api_key=api_key, temperature=temperature,
        )

    else:  # openai (default)
        model = runtime_model or settings.openai_model
        api_key = runtime_api_key or settings.openai_api_key
        base_url = runtime_base_url or settings.openai_base_url
        print(f"  ️  视觉 LLM: OpenAI {model}")

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
        "zhipu_model": settings.zhipu_model,
        "qwen_api_key": _mask_key(settings.qwen_api_key),
        "qwen_text_model": settings.qwen_text_model,
        "qwen_vision_model": settings.qwen_vision_model,
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
        "zhipu_model": "ZHIPU_MODEL",
        "qwen_api_key": "QWEN_API_KEY",
        "qwen_text_model": "QWEN_TEXT_MODEL",
        "qwen_vision_model": "QWEN_VISION_MODEL",
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
        "ZHIPU_MODEL": "zhipu_model",
        "QWEN_API_KEY": "qwen_api_key",
        "QWEN_TEXT_MODEL": "qwen_text_model",
        "QWEN_VISION_MODEL": "qwen_vision_model",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
    }
    for env_key, val in env_updates.items():
        attr = key_to_attr.get(env_key)
        if attr and hasattr(settings, attr):
            setattr(settings, attr, val)
    # 同时更新 os.environ，确保新进程可见
    for env_key, val in env_updates.items():
        os.environ[env_key] = val


# ═══════════════════════════════════════════════════════════
# Provider 注册表 — 各平台的文本/视觉模型元数据
# ═══════════════════════════════════════════════════════════

PROVIDER_REGISTRY = {
    "deepseek": {
        "name": "DeepSeek",
        "api_base": "https://api.deepseek.com/v1",
        "api_style": "openai",  # OpenAI 兼容 API
        "text_models": [
            {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro ", "desc": "最新旗舰，复杂任务首选 (推荐)"},
            {"id": "deepseek-chat", "name": "DeepSeek-V3.1 (Chat)", "desc": "通用对话，164K 上下文"},
            {"id": "deepseek-reasoner", "name": "DeepSeek-R1 (Reasoner)", "desc": "深度推理，适合复杂分析"},
        ],
        "vision_models": [],  # DeepSeek 无视觉能力
        "default_text_model": "deepseek-v4-pro",
        "default_vision_model": "",
        "note": "DeepSeek 不支持视觉分析，需另外配置视觉模型",
    },
    "qwen": {
        "name": "阿里千问 (Qwen)",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "qwen3.7-max-2026-06-08", "name": "Qwen3.7-Max", "desc": "顶级推理，最贵，复杂任务首选"},
            {"id": "qwen3.7-plus", "name": "Qwen3.7-Plus ", "desc": "旗舰平衡，256K 上下文 (推荐)"},
            {"id": "qwen3.6-plus", "name": "Qwen3.6-Plus", "desc": "上代旗舰，1M 上下文"},
            {"id": "qwen3.6-flash", "name": "Qwen3.6-Flash", "desc": "快速响应，1M 上下文"},
            {"id": "qwen3.5-plus", "name": "Qwen3.5-Plus", "desc": "高性价比，1M 上下文 (省钱)"},
            {"id": "qwen3.5-flash", "name": "Qwen3.5-Flash", "desc": "轻量快速，1M 上下文 (极速)"},
        ],
        "vision_models": [
            {"id": "qwen3.7-plus", "name": "Qwen3.7-Plus ", "desc": "原生多模态，256K 上下文 (推荐)"},
            {"id": "qwen3.6-plus", "name": "Qwen3.6-Plus", "desc": "原生多模态，1M 上下文"},
            {"id": "qwen3.6-flash", "name": "Qwen3.6-Flash", "desc": "快速视觉，1M 上下文"},
            {"id": "qwen3-vl-plus", "name": "Qwen3-VL-Plus", "desc": "专用视觉模型，262K 上下文"},
            {"id": "qwen3-vl-flash", "name": "Qwen3-VL-Flash", "desc": "轻量视觉，262K 上下文 (省钱)"},
        ],
        "default_text_model": "qwen3.7-plus",
        "default_vision_model": "qwen3.7-plus",
    },
    "zhipu": {
        "name": "智谱AI (GLM)",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "api_style": "openai",
        "text_models": [
            {"id": "GLM-5.1", "name": "GLM-5.1", "desc": "最新旗舰，Coding 对齐 Claude，200K"},
            {"id": "GLM-5", "name": "GLM-5", "desc": "高智能基座，Agentic 长程规划，200K"},
            {"id": "GLM-4.7", "name": "GLM-4.7", "desc": "Agentic Coding 强化，200K 上下文"},
            {"id": "GLM-4.7-Flash", "name": "GLM-4.7-Flash ", "desc": "免费旗舰普惠版，200K 上下文 (推荐)"},
        ],
        "vision_models": [
            {"id": "GLM-5V-Turbo", "name": "GLM-5V-Turbo ", "desc": "首个多模态Agent模型，200K (推荐)"},
            {"id": "GLM-4.6V", "name": "GLM-4.6V", "desc": "视觉推理 SOTA，原生 Function Call，128K"},
            {"id": "GLM-4.6V-Flash", "name": "GLM-4.6V-Flash", "desc": "免费轻量视觉推理，9B 参数"},
            {"id": "GLM-4V-Flash", "name": "GLM-4V-Flash", "desc": "免费图像理解，16K 上下文"},
            {"id": "GLM-4.1V-Thinking-Flash", "name": "GLM-4.1V-Thinking", "desc": "视觉推理，复杂场景，64K"},
        ],
        "default_text_model": "GLM-4.7-Flash",
        "default_vision_model": "GLM-4.6V",
    },
    "openai": {
        "name": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "gpt-4.1", "name": "GPT-4.1", "desc": "最新旗舰，1M 上下文，最强编码"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1-Mini", "desc": "平衡性价比，1M 上下文"},
            {"id": "gpt-4.1-nano", "name": "GPT-4.1-Nano", "desc": "极致便宜，1M 上下文"},
            {"id": "gpt-4o", "name": "GPT-4o ", "desc": "经典多模态旗舰，128K (推荐)"},
            {"id": "gpt-4o-mini", "name": "GPT-4o-Mini", "desc": "轻量多模态，128K，极便宜"},
            {"id": "o3", "name": "o3", "desc": "前沿推理，视觉+思维链，200K"},
            {"id": "o4-mini", "name": "o4-mini", "desc": "性价比推理+视觉，200K"},
        ],
        "vision_models": [
            {"id": "gpt-4.1", "name": "GPT-4.1 ", "desc": "最新视觉，1M 上下文 (推荐)"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1-Mini", "desc": "平衡视觉，1M 上下文"},
            {"id": "gpt-4o", "name": "GPT-4o", "desc": "经典多模态，128K"},
            {"id": "gpt-4o-mini", "name": "GPT-4o-Mini", "desc": "轻量视觉，128K，极便宜"},
            {"id": "o3", "name": "o3", "desc": "推理+视觉，思维链看图，200K"},
            {"id": "o4-mini", "name": "o4-mini", "desc": "性价比推理+视觉，200K"},
        ],
        "default_text_model": "gpt-4o",
        "default_vision_model": "gpt-4.1",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "api_base": "https://api.anthropic.com",
        "api_style": "anthropic",
        "text_models": [
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "desc": "最佳速度+智能平衡"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "desc": "最强旗舰"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "desc": "快速便宜"},
        ],
        "vision_models": [
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "desc": "最佳视觉+智能平衡"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "desc": "最强视觉理解"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "desc": "快速视觉，低成本"},
        ],
        "default_text_model": "claude-sonnet-4-6",
        "default_vision_model": "claude-sonnet-4-6",
    },
    # ── 国内厂商（OpenAI 兼容）──
    "moonshot": {
        "name": "月之暗面 Kimi",
        "api_base": "https://api.moonshot.cn/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "moonshot-v1-8k", "name": "Moonshot v1-8K", "desc": "通用对话，8K上下文"},
            {"id": "moonshot-v1-32k", "name": "Moonshot v1-32K", "desc": "超长文本，32K上下文"},
            {"id": "moonshot-v1-128k", "name": "Moonshot v1-128K", "desc": "长文档处理，128K上下文"},
            {"id": "kimi-latest", "name": "Kimi Latest", "desc": "最新模型，自动升级"},
        ],
        "vision_models": [],
        "default_text_model": "moonshot-v1-8k",
        "default_vision_model": "",
        "note": "Kimi 不支持视觉分析",
    },
    "doubao": {
        "name": "字节豆包 (火山引擎)",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "api_style": "openai",
        "text_models": [
            {"id": "doubao-pro-32k", "name": "豆包 Pro 32K", "desc": "旗舰模型，32K上下文"},
            {"id": "doubao-pro-128k", "name": "豆包 Pro 128K", "desc": "长上下文，128K"},
            {"id": "doubao-lite-32k", "name": "豆包 Lite 32K", "desc": "轻量快速，32K上下文"},
            {"id": "doubao-lite-128k", "name": "豆包 Lite 128K", "desc": "轻量长上下文，128K"},
        ],
        "vision_models": [
            {"id": "doubao-vision-pro-32k", "name": "豆包视觉 Pro", "desc": "多模态理解，32K"},
        ],
        "default_text_model": "doubao-pro-32k",
        "default_vision_model": "doubao-vision-pro-32k",
    },
    "lingyi": {
        "name": "零一万物 Yi",
        "api_base": "https://api.lingyiwanwu.com/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "yi-large", "name": "Yi-Large", "desc": "大杯旗舰模型"},
            {"id": "yi-medium", "name": "Yi-Medium", "desc": "中杯平衡模型"},
            {"id": "yi-lightning", "name": "Yi-Lightning", "desc": "极速响应"},
        ],
        "vision_models": [
            {"id": "yi-vision", "name": "Yi-Vision", "desc": "多模态视觉理解"},
        ],
        "default_text_model": "yi-large",
        "default_vision_model": "yi-vision",
    },
    "minimax": {
        "name": "MiniMax (海螺AI)",
        "api_base": "https://api.minimax.chat/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "abab6.5s-chat", "name": "ABAB 6.5s", "desc": "日常对话模型"},
            {"id": "abab6.5t-chat", "name": "ABAB 6.5t", "desc": "长文本处理"},
            {"id": "abab5.5-chat", "name": "ABAB 5.5", "desc": "轻量快速"},
        ],
        "vision_models": [],
        "default_text_model": "abab6.5s-chat",
        "default_vision_model": "",
        "note": "MiniMax 不支持视觉分析",
    },
    "baichuan": {
        "name": "百川智能",
        "api_base": "https://api.baichuan-ai.com/v1",
        "api_style": "openai",
        "text_models": [
            {"id": "Baichuan4", "name": "百川 4", "desc": "最新旗舰模型"},
            {"id": "Baichuan3-Turbo", "name": "百川 3 Turbo", "desc": "快速响应"},
            {"id": "Baichuan2-Turbo", "name": "百川 2 Turbo", "desc": "轻量模型"},
        ],
        "vision_models": [],
        "default_text_model": "Baichuan4",
        "default_vision_model": "",
        "note": "百川不支持视觉分析",
    },
}

# 生成前端可用的简化列表
def get_providers_for_frontend() -> list[dict]:
    """返回前端需要的 provider 列表（不含 API base 等敏感信息）."""
    providers = []
    for key, info in PROVIDER_REGISTRY.items():
        providers.append({
            "id": key,
            "name": info["name"],
            "has_vision": len(info.get("vision_models", [])) > 0,
            "text_models": info.get("text_models", []),
            "vision_models": info.get("vision_models", []),
            "default_text_model": info.get("default_text_model", ""),
            "default_vision_model": info.get("default_vision_model", ""),
            "note": info.get("note", ""),
        })
    return providers
