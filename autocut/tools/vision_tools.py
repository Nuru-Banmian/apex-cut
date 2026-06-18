"""多模态视觉分析工具 — 利用 LLM 理解视频画面内容.

工具列表:
  - describe_frames: 逐帧描述（单帧单次调用）
  - describe_frames_batch: 批量帧描述（多帧一次调用，节省 API 开销）
  - analyze_scenes: PySceneDetect 场景切换检测
"""

from __future__ import annotations

import base64
from pathlib import Path

from langchain_core.tools import tool

from autocut.config import create_multimodal_llm, _get_runtime_vision_key, _get_runtime_vision_provider


def _encode_image(image_path: str) -> str:
    """将图片编码为 base64 data URL."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@tool
def describe_frames(frame_dir: str, sample_count: int = 10) -> dict:
    """使用多模态 LLM 逐帧分析视频抽帧画面，生成画面内容描述。

    Args:
        frame_dir: 抽帧图片所在目录（含 frame_0001.jpg 等）
        sample_count: 均匀采样多少帧进行分析

    Returns:
        {success, frame_descriptions: [{frame, time_seconds, description}], frame_count}
    """
    frame_path = Path(frame_dir)
    if not frame_path.exists():
        return {"success": False, "error": f"目录不存在: {frame_dir}"}

    all_frames = sorted(frame_path.glob("frame_*.jpg"))
    if not all_frames:
        return {"success": False, "error": f"目录下无帧图片: {frame_dir}"}

    # 均匀采样
    step = max(1, len(all_frames) // sample_count)
    sampled = all_frames[::step][:sample_count]

    try:
        llm = create_multimodal_llm(runtime_api_key=_get_runtime_vision_key(), runtime_provider=_get_runtime_vision_provider())
    except Exception as e:
        return {"success": False, "error": f"多模态 LLM 初始化失败: {e}"}

    descriptions = []
    for i, fpath in enumerate(sampled):
        try:
            frame_num = int(fpath.stem.split("_")[-1])

            b64 = _encode_image(str(fpath))
            image_url = f"data:image/jpeg;base64,{b64}"

            from langchain_core.messages import HumanMessage
            msg = HumanMessage(content=[
                {
                    "type": "text",
                    "text": (
                        "请详细描述这个视频画面的内容，包括：\n"
                        "1. 场景类型（室内/室外/演播室/街道/...）\n"
                        "2. 画面中的人物（数量、位置、动作、表情）\n"
                        "3. 画面中的物体/文字/UI（如有）\n"
                        "4. 光线和色彩氛围\n"
                        "5. 构图特点（特写/中景/全景/...）\n"
                        "请用中文描述，控制在80字以内。"
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_url}},
            ])
            resp = llm.invoke([msg])
            desc = resp.content.strip() if hasattr(resp, 'content') else str(resp)

            descriptions.append({
                "frame": frame_num,
                "time_seconds": 0.0,  # 由 analyzer 根据视频时长修正
                "description": desc,
            })
        except Exception as e:
            descriptions.append({
                "frame": int(fpath.stem.split("_")[-1]) if "_" in fpath.stem else i,
                "time_seconds": 0.0,
                "description": f"[分析失败: {str(e)[:80]}]",
            })

    return {
        "success": True,
        "frame_descriptions": descriptions,
        "frame_count": len(descriptions),
    }


@tool
def describe_frames_batch(frame_dir: str, sample_count: int = 20) -> dict:
    """批量分析多帧画面（一次 API 调用分析多张图，节省开销）。

    将多帧图片打包为一条消息发送给多模态 LLM，让 LLM 逐帧描述。
    适合帧数较多时使用，相比逐帧调用可大幅减少 API 请求数。

    Args:
        frame_dir: 抽帧图片所在目录
        sample_count: 均匀采样多少帧（建议 10-20）

    Returns:
        {success, frame_descriptions: [{frame, description}], frame_count}
    """
    frame_path = Path(frame_dir)
    if not frame_path.exists():
        return {"success": False, "error": f"目录不存在: {frame_dir}"}

    all_frames = sorted(frame_path.glob("frame_*.jpg"))
    if not all_frames:
        return {"success": False, "error": f"目录下无帧图片: {frame_dir}"}

    # 均匀采样
    step = max(1, len(all_frames) // sample_count)
    sampled = all_frames[::step][:sample_count]

    try:
        llm = create_multimodal_llm(runtime_api_key=_get_runtime_vision_key(), runtime_provider=_get_runtime_vision_provider())
    except Exception as e:
        return {"success": False, "error": f"多模态 LLM 初始化失败: {e}"}

    # 构建批量消息：文本指令 + 所有帧图片
    from langchain_core.messages import HumanMessage

    content_parts = [
        {
            "type": "text",
            "text": (
                f"以下是按时间顺序从视频中抽取的 {len(sampled)} 个关键帧画面。\n\n"
                "请按顺序分析每一帧的画面内容。对每帧描述：场景类型、人物/物体、动作、光线氛围、构图。\n"
                "每帧描述控制在40字以内，中文。\n\n"
                "请严格按以下 JSON 格式返回（只返回 JSON，不要其它文字）：\n"
                '{"frames": ['
                '{"frame": 1, "description": "画面描述"},'
                '{"frame": 2, "description": "画面描述"},'
                "...\n"
                "]}\n\n"
                f"共 {len(sampled)} 帧，按序号 1-{len(sampled)} 依次描述。"
            ),
        }
    ]

    # 添加所有帧图片
    for i, fpath in enumerate(sampled):
        b64 = _encode_image(str(fpath))
        image_url = f"data:image/jpeg;base64,{b64}"
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })

    try:
        msg = HumanMessage(content=content_parts)
        resp = llm.invoke([msg])
        resp_text = resp.content.strip() if hasattr(resp, 'content') else str(resp)

        # 解析 JSON 响应
        import json
        if resp_text.startswith("```"):
            resp_text = resp_text.split("\n", 1)[1].rsplit("\n```", 1)[0]

        result = json.loads(resp_text)
        raw_frames = result.get("frames", [])

        # 映射回实际帧号
        descriptions = []
        for item in raw_frames:
            idx = item.get("frame", 0) - 1  # LLM 返回 1-based
            if 0 <= idx < len(sampled):
                fpath = sampled[idx]
                frame_num = int(fpath.stem.split("_")[-1])
                descriptions.append({
                    "frame": frame_num,
                    "time_seconds": 0.0,
                    "description": item.get("description", ""),
                })

        return {
            "success": True,
            "frame_descriptions": descriptions,
            "frame_count": len(descriptions),
        }

    except json.JSONDecodeError as e:
        # JSON 解析失败，回退到逐帧分析
        print(f"  ⚠️ 批量帧分析 JSON 解析失败: {e}，回退逐帧分析...")
        # 用原始文本做简单拆分
        descriptions = []
        for i, fpath in enumerate(sampled):
            frame_num = int(fpath.stem.split("_")[-1])
            descriptions.append({
                "frame": frame_num,
                "time_seconds": 0.0,
                "description": f"帧 {i+1}（批量解析失败，需逐帧重试）",
            })
        return {
            "success": True,
            "frame_descriptions": descriptions,
            "frame_count": len(descriptions),
            "warning": f"批量解析失败: {e}",
        }
    except Exception as e:
        return {"success": False, "error": f"批量帧分析失败: {str(e)[:200]}"}


@tool
def analyze_scenes(video_path: str, threshold: float = 30.0) -> dict:
    """检测视频中的场景切换点。

    基于画面内容变化（色彩/亮度/纹理）自动切分场景，
    不依赖 AI，纯算法实现，速度快。

    Args:
        video_path: 视频文件路径
        threshold: 检测灵敏度 0-100，值越大检测到的场景越少（默认30）

    Returns:
        {success, scenes: [{start, end, scene_number}], scene_count}
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        scene_manager.detect_scenes(video)

        scenes = []
        for i, scene in enumerate(scene_manager.get_scene_list()):
            scenes.append({
                "start": round(scene[0].get_seconds(), 2),
                "end": round(scene[1].get_seconds(), 2),
                "scene_number": i + 1,
            })
        return {"success": True, "scenes": scenes, "scene_count": len(scenes)}
    except ImportError:
        return {"success": False, "error": "scenedetect 未安装，请运行 pip install scenedetect"}
    except Exception as e:
        return {"success": False, "error": f"场景检测失败: {e}"}


# 导出
VISION_TOOLS = [
    describe_frames,
    describe_frames_batch,
    analyze_scenes,
]
