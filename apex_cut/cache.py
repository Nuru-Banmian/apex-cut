"""分析结果缓存 — 侧挂目录，跟着视频走.

缓存结构（侧挂于视频旁边）:

    素材库/
    ├── 旅行vlog.mp4
    ├── 旅行vlog.mp4.apexcut/     ← 分析缓存目录
    │   ├── meta.json             # 元信息（此文件存在 = 缓存有效）
    │   ├── probe.json            # 视频元信息 {duration, width, height, fps, ...}
    │   ├── transcript.json       # 语音转写 [{start, end, text, confidence}, ...]
    │   ├── silences.json         # 静音检测 [{start, end, duration}, ...]
    │   ├── energy.json           # 音频能量 {energy_per_second, peak_times}
    │   ├── frame_labels.json     # 画面 UI 数据 [{frame, time_seconds, _changes, _event}, ...]
    │   └── meta.json
    └── 教程.mp4

使用方式:
    from apex_cut.cache import load_cache, save_cache, has_cache, delete_cache, rename_cache
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

CACHE_VERSION = 3

# 数据字段 → 文件名映射
FIELD_FILES = {
    "probe_info":       "probe.json",
    "frame_labels":     "frame_labels.json",              # Apex 专用：视觉读取的 UI 数据
}


def _cache_dir(video_path: str) -> Path | None:
    """视频对应的侧挂缓存目录: {video_path}.apexcut/"""
    p = Path(video_path).resolve()
    if not p.exists():
        return None
    return Path(str(p) + ".apexcut")


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

def has_cache(video_path: str, frame_interval: float = 0, max_vision_frames: int = 0) -> bool:
    """检查是否有该视频的分析缓存（meta.json 存在且视频未变 + 参数匹配）."""
    cache_dir = _cache_dir(video_path)
    if not cache_dir:
        return False
    meta_file = cache_dir / "meta.json"
    if not meta_file.exists():
        return False
    # 验证视频文件未变（size + mtime）
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        p = Path(video_path).resolve()
        if p.exists():
            stat = p.stat()
            if (meta.get("video_size") != stat.st_size or
                meta.get("video_mtime") != stat.st_mtime):
                print(f"[ 缓存] ️ 视频已变更，缓存失效")
                return False
        # 参数匹配：抽帧间隔或最大帧数变了 → 缓存不适用
        cached_interval = meta.get("frame_interval", 0)
        cached_max_frames = meta.get("max_vision_frames", 0)
        if (frame_interval > 0 and cached_interval > 0 and abs(frame_interval - cached_interval) > 0.01):
            print(f"[ 缓存] ️ 抽帧间隔已变 ({cached_interval}s → {frame_interval}s)，缓存失效")
            return False
        if (max_vision_frames > 0 and cached_max_frames > 0 and max_vision_frames != cached_max_frames):
            print(f"[ 缓存] ️ 最大帧数已变 ({cached_max_frames} → {max_vision_frames})，缓存失效")
            return False
    except Exception:
        return False
    return True


def load_cache(video_path: str) -> dict | None:
    """加载缓存的分析结果（按需读取各文件，组合成 dict）."""
    cache_dir = _cache_dir(video_path)
    if not cache_dir:
        return None

    meta_file = cache_dir / "meta.json"
    if not meta_file.exists():
        return None

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        print(f"[ 缓存] ️ meta.json 损坏: {e}")
        return None

    # 检查版本兼容
    if meta.get("version", 0) != CACHE_VERSION:
        print(f"[ 缓存] ️ 缓存版本不兼容 (v{meta.get('version')} → v{CACHE_VERSION})")
        return None

    data = {}
    loaded_files = []
    missing_files = []

    # 按 FIELD_FILES 加载各文件
    for field, filename in FIELD_FILES.items():
        filepath = cache_dir / filename
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = json.load(f)
                data[field] = content
                loaded_files.append(filename)
            except Exception as e:
                print(f"[ 缓存] ️ {filename} 损坏: {e}")
                missing_files.append(filename)
        else:
            missing_files.append(filename)

    if loaded_files:
        size_mb = sum((cache_dir / f).stat().st_size for f in set(loaded_files)) / 1048576
        print(f"[ 缓存]  命中 {len(loaded_files)} 个文件 ({size_mb:.1f}MB)" +
              (f" | 缺失: {missing_files}" if missing_files else ""))
        return data

    print(f"[ 缓存] ️ 无可用缓存文件")
    return None


def save_cache(video_path: str, data: dict, frame_interval: float = 0, max_vision_frames: int = 0):
    """保存分析结果到侧挂缓存目录（meta.json 最后写作为完成信号）."""
    cache_dir = _cache_dir(video_path)
    if not cache_dir:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)

    p = Path(video_path).resolve()
    video_stat = p.stat() if p.exists() else None

    # 按文件名聚合数据（多个字段可能存同一文件）
    file_data: dict[str, dict] = {}
    for field, filename in FIELD_FILES.items():
        if field not in data:
            continue
        value = data[field]
        if value is None:
            continue
        # 允许空列表 — 表示"分析跑了但没数据"，区别于"没跑过"
        if isinstance(value, list) and len(value) == 0:
            pass  # 仍然保存
        if filename not in file_data:
            file_data[filename] = {}
        file_data[filename][field] = value

    # 逐文件写入
    saved_files = {}
    for filename, fields in file_data.items():
        filepath = cache_dir / filename
        try:
            payload = _clean(list(fields.values())[0])

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, default=str)
            saved_files[filename] = filepath.stat().st_size
        except Exception as e:
            print(f"[ 缓存] ️ {filename} 写入失败: {e}")

    # meta.json 最后写入（作为"缓存完成"的信号）
    meta = {
        "version": CACHE_VERSION,
        "video_path": str(p),
        "video_size": video_stat.st_size if video_stat else 0,
        "video_mtime": video_stat.st_mtime if video_stat else 0,
        "cached_at": time.time(),
        "files": saved_files,
        "frame_interval": frame_interval,
        "max_vision_frames": max_vision_frames,
    }
    try:
        with open(cache_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, default=str)
        total_kb = sum(saved_files.values()) / 1024
        print(f"[ 缓存]  已保存 {len(saved_files)} 个文件 ({total_kb:.0f}KB) → {cache_dir}")
    except Exception as e:
        print(f"[ 缓存] ️ meta.json 写入失败: {e}")


def delete_cache(video_path: str) -> bool:
    """删除指定视频的侧挂缓存目录."""
    cache_dir = Path(str(Path(video_path).resolve()) + ".apexcut")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print(f"[ 缓存] ️ 已删除: {cache_dir}")
        return True
    return False


def rename_cache(old_path: str, new_path: str) -> bool:
    """视频重命名后同步重命名缓存目录."""
    old_cache = Path(str(Path(old_path).resolve()) + ".apexcut")
    new_cache = Path(str(Path(new_path).resolve()) + ".apexcut")

    if not old_cache.exists():
        return False  # 没有缓存，无需操作

    try:
        # 更新 meta.json 中的 video_path
        meta_file = old_cache / "meta.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["video_path"] = str(Path(new_path).resolve())
            # 先写临时文件再替换，避免断电损坏
            tmp = old_cache / "meta.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, default=str)
            tmp.replace(meta_file)

        # 重命名缓存目录
        old_cache.rename(new_cache)
        print(f"[ 缓存]  已同步重命名: {old_cache.name} → {new_cache.name}")
        return True
    except Exception as e:
        print(f"[ 缓存] ️ 重命名失败: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════

def _clean(obj):
    """清洗数据，确保 JSON 可序列化."""
    try:
        json.dumps(obj, ensure_ascii=False, default=str)
        return obj
    except (TypeError, ValueError):
        if isinstance(obj, list):
            return [_clean(it) for it in obj[:500]]
        if isinstance(obj, dict):
            return {str(k): _clean(v) for k, v in list(obj.items())[:500]}
        return str(obj)[:500]
