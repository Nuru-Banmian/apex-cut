"""缓存加载 Agent — 侧挂缓存命中时跳过 Analyzer，直接加载数据进 State."""

from __future__ import annotations

from apex_cut.state import VideoEditState
from apex_cut.cache import has_cache, load_cache


def cache_loader_node(state: VideoEditState) -> dict:
    """从侧挂缓存加载分析数据，跳过视频分析."""
    video_path = state.get("video_path", "")

    print(f"\n{'='*60}")
    print(f"[ 缓存加载] 检测到已分析缓存，跳过视频分析")
    print(f"[ 缓存加载] 视频: {video_path}")
    print(f"{'='*60}")

    if not video_path:
        return {"error": "未提供视频路径"}

    if not has_cache(video_path):
        print(f"[ 缓存加载] ️ 缓存已失效，回退到分析流程")
        return {"_cache_miss": True}

    raw = load_cache(video_path)
    if not raw:
        print(f"[ 缓存加载] ️ 缓存加载失败，回退到分析流程")
        return {"_cache_miss": True}

    # ── 拆包原始数据 ──
    frame_labels = raw.get("frame_labels", [])
    probe_info = raw.get("probe_info", {})

    duration = probe_info.get("duration", 0)
    width = probe_info.get("width", 0)
    height = probe_info.get("height", 0)

    print(f"   视频: {duration:.1f}s, {width}x{height}")
    print(f"  ️ 帧标签: {len(frame_labels)}帧")

    # 帧标签统计
    combat_frames = sum(1 for f in frame_labels if f.get("_changes", {}).get("in_combat"))
    kill_frames = sum(1 for f in frame_labels if f.get("_changes", {}).get("kill_occurred"))
    assist_frames = sum(1 for f in frame_labels if f.get("_changes", {}).get("assist_occurred"))
    if combat_frames:
        print(f"  ️  战斗={combat_frames} 击杀={kill_frames} 助攻={assist_frames}")

    # 检查是否只有原始数据但缺帧标签
    has_raw = bool(probe_info)
    if has_raw and not frame_labels:
        print(f"  ️ 有原始数据但缺帧标签 → 重跑视觉分析")
        print(f"{'='*60}")
        return {"_cache_miss": True}

    print(f"{'='*60}")

    return {
        "frame_labels": frame_labels,
        "_from_cache": True,
    }
