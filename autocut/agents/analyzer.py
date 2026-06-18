"""分析 Agent — 音频 + 画面并重的深度内容分析.

流程（三阶段）:
  Step 1 — 并行工具采集: probe / extract_frames / transcribe / silence / energy / scenes
  Step 2 — 画面理解: 多模态 LLM 逐帧描述画面内容（describe_frames）
  Step 3 — 融合分析: LLM 综合音频+画面+转写 → 内容理解 / 情绪曲线 / 叙事结构 / 标签

设计原则:
  - 音频分析和画面分析地位完全平等
  - 画面理解需要 OpenAI 视觉 Key（可选，无 Key 时跳过）
  - 所有本地工具调用不经过 LLM，直接执行
  - LLM 只做决策和语义理解
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from autocut.state import VideoEditState
from autocut.config import create_llm, _extract_runtime_keys, OUTPUT_DIR, _get_runtime_vision_key, settings
from autocut.errors import check_and_raise
from autocut.tools.video_tools import get_ffmpeg


# ═══════════════════════════════════════════════════════════
# 融合分析 System Prompt
# ═══════════════════════════════════════════════════════════

FUSION_SYSTEM_PROMPT = """你是专业的视频内容分析师。你的任务是将音频分析和画面分析的结果融合起来，生成对视频内容的深度理解。

你会收到以下数据:
1. **视频基本信息**: 时长、分辨率、帧率
2. **音频维度**:
   - 语音转写（前200句）: [{start, end, text, confidence}]
   - 静音区间: [{start, end, duration}]
   - 音频能量峰值: [{time, energy}]
3. **画面维度**:
   - 场景切分: [{start, end, scene_number}]
   - 关键帧画面描述: [{time_seconds, description}]
4. **用户需求**: 用户对视频的分析需求

请返回以下 JSON 结构（务必返回有效 JSON）:

{
    "content_summary": "视频的完整内容概述（3-5句话），结合画面内容和语音内容综合描述",
    "content_tags": ["标签1", "标签2", ...],  // 内容类型标签: 教程/产品演示/访谈/Vlog/演讲/纪录片/娱乐/...
    "mood": "整体情绪基调",  // energetic / calm / emotional / professional / humorous / dramatic / casual
    "mood_curve": [
        {"time": 0.0, "mood": "opening", "confidence": 0.8},
        {"time": 30.0, "mood": "energetic", "confidence": 0.9},
        ...
    ],  // 情绪随时间变化的曲线，每30秒一个采样点，或情绪变化明显处标记
    "narrative_structure": {
        "intro": {"start": 0.0, "end": 10.0, "description": "开场介绍..."},
        "body": {"start": 10.0, "end": 80.0, "description": "主体内容..."},
        "climax": {"start": 50.0, "end": 70.0, "description": "高潮部分..."},
        "outro": {"start": 80.0, "end": 90.0, "description": "结尾..."}
    },  // 叙事结构拆解，根据视频实际内容灵活标注
    "highlights": [
        {"start": 15.0, "end": 25.0, "score": 9, "reason": "为什么精彩——结合画面和语音判断"}
    ],  // 精彩片段，综合画面信息密度+音频能量+转写金句
    "quality_issues": [
        {"start": 5.0, "end": 8.0, "issue_type": "silence/long_pause/blur/...", "severity": "high/medium/low", "detail": "问题描述"}
    ],
    "scene_analyses": [
        {
            "scene": 1,
            "start": 0.0,
            "end": 30.0,
            "visual": "这个场景的画面内容是什么",
            "audio": "这个场景的音频内容是什么",
            "summary": "这个场景的综合描述"
        }
    ]
}

分析原则:
- 综合利用音频和画面信息，两者权重相等
- 善用画面描述来理解视觉场景、人物动作、环境氛围
- 善用转写文本来理解语义、主题、金句
- 善用音频能量来识别情绪高点
- 叙事结构根据实际内容灵活标注，不强制套模板
- interestingness 综合考虑: 画面变化 + 语音信息密度 + 音频能量
- 标签要具体（如"AI工具使用教程"而非仅"教程"）

只返回 JSON，不要其他任何内容。"""


# ═══════════════════════════════════════════════════════════
# 主分析节点
# ═══════════════════════════════════════════════════════════

def analyzer_node(state: VideoEditState) -> dict:
    """深度分析节点 — 音频 + 画面并重.

    三阶段:
      Step 1: 并行工具采集（probe / frames / transcribe / silence / energy / scenes）
      Step 2: 画面理解（多模态 LLM 描述帧内容）
      Step 3: LLM 融合分析
    """
    video_path = state.get("video_path", "")
    requirement = state.get("user_requirement", "")

    print(f"\n{'='*60}")
    print(f"[🔍 深度分析] 开始分析视频")
    print(f"[🔍 深度分析] 视频: {video_path}")
    print(f"[🔍 深度分析] 需求: {requirement[:80]}{'...' if len(requirement) > 80 else ''}")
    print(f"{'='*60}")

    if not video_path:
        return {"error": "未提供视频路径"}

    provider, api_key, api_base = _extract_runtime_keys(state)
    vision_key = state.get("runtime_vision_key", "") or _get_runtime_vision_key()
    # 回退到 .env 中的视觉 Key（CLI 模式或未传运行时 Key 时）
    if not vision_key:
        vision_provider = state.get("runtime_vision_provider", "") or settings.vision_provider
        if vision_provider == "zhipu":
            vision_key = settings.zhipu_api_key
        elif vision_provider == "qwen":
            vision_key = settings.qwen_api_key
        else:  # openai
            vision_key = settings.openai_api_key

    # ═══════════════════════════════════════════════════════
    # Step 1: 并行工具采集 — 音频+画面基础数据
    # ═══════════════════════════════════════════════════════
    print(f"\n[🔍 Step 1/3] 并行采集基础数据...")
    print(f"{'─'*40}")

    tool = get_ffmpeg()

    # 1a. 视频元信息
    probe_result = _call_probe(video_path)
    duration = probe_result.get("duration", 0) if probe_result else 0
    width = probe_result.get("width", 0) if probe_result else 0
    height = probe_result.get("height", 0) if probe_result else 0
    fps = probe_result.get("fps", 0) if probe_result else 0
    print(f"  📹 视频信息: {duration:.1f}s, {width}x{height}, {fps}fps")

    # 1b. 抽帧（为画面理解准备）
    frame_dir = str(OUTPUT_DIR / "frames")
    frame_count = 0
    try:
        # 根据视频长度自适应抽帧间隔
        if duration <= 60:
            interval = 2.0   # 短视频密集抽帧
        elif duration <= 300:
            interval = 5.0   # 中等视频
        elif duration <= 900:
            interval = 8.0   # 长视频
        else:
            interval = 12.0  # 超长视频

        max_frames = min(60, int(duration / interval) + 1)  # 最多60帧
        frame_result = tool.extract_frames(video_path, interval=interval,
                                           output_dir=frame_dir, max_frames=max_frames)
        frame_count = frame_result.get("frame_count", 0) if frame_result["success"] else 0
        print(f"  🖼️  抽帧: {frame_count} 张 (间隔 {interval}s)")
    except Exception as e:
        print(f"  🖼️  抽帧: 失败 ({e})")
        frame_count = 0

    # 1c. 语音转写
    transcript = _call_transcribe(video_path)
    print(f"  🎤 语音转写: {len(transcript)} 段")

    # 1d. 静音检测
    silences = _call_detect_silence(video_path)
    print(f"  🔇 静音检测: {len(silences)} 段")

    # 1e. 音频能量分析
    energy_result = _call_audio_energy(video_path)
    energy_per_sec = energy_result.get("energy_per_second", []) if energy_result else []
    energy_peaks = energy_result.get("peak_times", []) if energy_result else []
    print(f"  📊 音频能量: {len(energy_per_sec)}s 数据, {len(energy_peaks)} 个峰值")

    # 1f. 场景检测
    scenes = _call_analyze_scenes(video_path)
    print(f"  🎬 场景检测: {len(scenes)} 个场景")

    # ═══════════════════════════════════════════════════════
    # Step 2: 画面理解 — 多模态 LLM 描述帧内容
    # ═══════════════════════════════════════════════════════
    print(f"\n[🔍 Step 2/3] 画面内容理解...")
    print(f"{'─'*40}")

    frame_descriptions = []

    if frame_count > 0 and vision_key:
        try:
            from autocut.tools.vision_tools import describe_frames_batch

            # 根据帧数自适应采样
            sample_count = min(frame_count, 20)  # 最多分析20帧
            result = describe_frames_batch.invoke({
                "frame_dir": frame_dir,
                "sample_count": sample_count,
            })

            if result.get("success"):
                frame_descriptions = result.get("frame_descriptions", [])
                # 补充实际时间戳
                frame_descriptions = _fix_frame_timestamps(
                    frame_descriptions, frame_dir, duration, frame_count
                )
                print(f"  👁️  画面描述: {len(frame_descriptions)} 帧完成")
            else:
                print(f"  👁️  画面描述: 失败 - {result.get('error', '未知')[:100]}")

        except Exception as e:
            print(f"  👁️  画面描述: 异常 - {e}")
    elif frame_count > 0 and not vision_key:
        print(f"  👁️  画面描述: 跳过（未配置视觉 Key，仅分析音频）")
    else:
        print(f"  👁️  画面描述: 跳过（无可用帧）")

    # ═══════════════════════════════════════════════════════
    # Step 3: LLM 融合分析 — 音频+画面+转写综合理解
    # ═══════════════════════════════════════════════════════
    print(f"\n[🔍 Step 3/3] LLM 融合分析...")
    print(f"{'─'*40}")

    highlights = []
    quality_issues = []
    content_summary = ""
    content_tags = []
    mood = ""
    mood_curve = []
    narrative_structure = {}
    scene_analyses = []

    # 构建融合分析的上下文
    fusion_context = _build_fusion_context(
        duration=duration,
        width=width, height=height, fps=fps,
        transcript=transcript,
        silences=silences,
        energy_peaks=energy_peaks,
        scenes=scenes,
        frame_descriptions=frame_descriptions,
        requirement=requirement,
        has_visual=(len(frame_descriptions) > 0),
    )

    try:
        llm = create_llm(temperature=0.4, runtime_provider=provider,
                         runtime_api_key=api_key, runtime_base_url=api_base)

        fusion_text = json.dumps(fusion_context, ensure_ascii=False, default=str)
        # 限制 context 长度，避免超限
        max_context = 12000
        if len(fusion_text) > max_context:
            fusion_text = fusion_text[:max_context]
            print(f"  ⚠️ Context 截断至 {max_context} 字符")

        response = llm.invoke([
            SystemMessage(content=FUSION_SYSTEM_PROMPT),
            HumanMessage(content=fusion_text),
        ])

        resp_content = response.content if hasattr(response, "content") else str(response)
        resp_content = resp_content.strip()
        if resp_content.startswith("```"):
            resp_content = resp_content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        result = json.loads(resp_content)
        highlights = result.get("highlights", [])
        quality_issues = result.get("quality_issues", [])
        content_summary = result.get("content_summary", "")
        content_tags = result.get("content_tags", [])
        mood = result.get("mood", "")
        mood_curve = result.get("mood_curve", [])
        narrative_structure = result.get("narrative_structure", {})
        scene_analyses = result.get("scene_analyses", [])

        # 合并代码侧检测的静音问题（确保不遗漏）
        _merge_silence_issues(quality_issues, silences)

        print(f"  ✅ 融合分析完成")
        print(f"  摘要: {content_summary[:100]}{'...' if len(content_summary) > 100 else ''}")
        print(f"  标签: {', '.join(content_tags) if content_tags else '无'}")
        print(f"  情绪: {mood}")
        print(f"  精彩片段: {len(highlights)} 个")
        print(f"  问题标记: {len(quality_issues)} 处")
        print(f"  场景分析: {len(scene_analyses)} 个")
        print(f"  叙事结构: {len(narrative_structure)} 段")

    except Exception as e:
        check_and_raise(e, "分析")
        print(f"  ❌ 融合分析失败: {e}")
        # 回退：仅用代码侧数据
        content_summary = _build_fallback_summary(transcript, duration, scenes)
        _merge_silence_issues(quality_issues, silences)
        print(f"  已回退到基础分析")

    # ═══════════════════════════════════════════════════════
    # 汇总输出
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print(f"[🔍 深度分析] 完成!")
    print(f"  音频: {len(transcript)} 转写段 / {len(silences)} 静音 / {len(energy_peaks)} 能量峰")
    print(f"  画面: {frame_count} 抽帧 / {len(frame_descriptions)} 画面描述 / {len(scenes)} 场景")
    print(f"  融合: {len(highlights)} 亮点 / {len(content_tags)} 标签 / {len(scene_analyses)} 场景分析")
    print(f"{'='*60}")

    return {
        # 音频维度
        "transcript": transcript,
        "silences": silences,
        "audio_energy": energy_per_sec,
        "energy_peaks": energy_peaks,
        # 画面维度
        "scenes": scenes,
        "frame_descriptions": frame_descriptions,
        # 融合分析
        "highlights": highlights,
        "quality_issues": quality_issues,
        "content_summary": content_summary,
        "content_tags": content_tags,
        "mood": mood,
        "mood_curve": mood_curve,
        "narrative_structure": narrative_structure,
        "scene_analyses": scene_analyses,
    }


# ═══════════════════════════════════════════════════════════
# 本地工具调用（不经过 LLM）
# ═══════════════════════════════════════════════════════════

def _call_probe(video_path: str) -> dict | None:
    try:
        r = get_ffmpeg().probe(video_path)
        return r.get("info", {}) if r.get("success") else None
    except Exception:
        return None


def _call_transcribe(video_path: str) -> list[dict]:
    try:
        from autocut.tools.audio_tools import transcribe_audio
        r = transcribe_audio.invoke({"video_path": video_path, "language": "zh"})
        return r.get("transcript", []) if r.get("success") else []
    except Exception as e:
        print(f"  ⚠️ transcribe 失败: {e}")
        return []


def _call_detect_silence(video_path: str) -> list[dict]:
    try:
        from autocut.tools.audio_tools import detect_silence
        r = detect_silence.invoke({"video_path": video_path, "min_silence_duration": 0.8})
        return r.get("silences", []) if r.get("success") else []
    except Exception as e:
        print(f"  ⚠️ silence detect 失败: {e}")
        return []


def _call_audio_energy(video_path: str) -> dict | None:
    try:
        from autocut.tools.audio_tools import analyze_audio_energy
        r = analyze_audio_energy.invoke({"video_path": video_path})
        return r if r.get("success") else None
    except Exception as e:
        print(f"  ⚠️ audio energy 失败: {e}")
        return None


def _call_analyze_scenes(video_path: str) -> list[dict]:
    try:
        from autocut.tools.vision_tools import analyze_scenes
        r = analyze_scenes.invoke({"video_path": video_path, "threshold": 30.0})
        return r.get("scenes", []) if r.get("success") else []
    except Exception as e:
        print(f"  ⚠️ scene detect 失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _build_fusion_context(
    duration: float,
    width: int, height: int, fps: float,
    transcript: list[dict],
    silences: list[dict],
    energy_peaks: list[dict],
    scenes: list[dict],
    frame_descriptions: list[dict],
    requirement: str,
    has_visual: bool,
) -> dict:
    """构建传给融合 LLM 的分析上下文.

    控制每个维度的数据量，避免超过 LLM context 限制.
    """
    ctx = {
        "video_info": {
            "duration_seconds": round(duration, 1),
            "resolution": f"{width}x{height}",
            "fps": fps,
            "duration_display": f"{int(duration//60)}分{int(duration%60)}秒",
        },
        "user_requirement": requirement,
        "has_visual_analysis": has_visual,
    }

    # 音频：转写（前200句）
    if transcript:
        ctx["audio_transcript"] = transcript[:200]
        ctx["audio_transcript_total"] = len(transcript)

    # 音频：静音区间（取最长的30段）
    if silences:
        sorted_silences = sorted(silences, key=lambda s: s.get("duration", 0), reverse=True)
        ctx["audio_silences"] = sorted_silences[:30]
        ctx["audio_silences_total"] = len(silences)

    # 音频：能量峰值（取最高的30个）
    if energy_peaks:
        sorted_peaks = sorted(energy_peaks, key=lambda p: p.get("energy", 0), reverse=True)
        ctx["audio_energy_peaks"] = sorted_peaks[:30]

    # 画面：场景切分
    if scenes:
        ctx["visual_scenes"] = scenes[:30]

    # 画面：帧描述
    if frame_descriptions:
        ctx["visual_frame_descriptions"] = frame_descriptions[:20]

    return ctx


def _fix_frame_timestamps(
    descriptions: list[dict],
    frame_dir: str,
    duration: float,
    total_frames: int,
) -> list[dict]:
    """修正帧描述中的时间戳（根据帧序号和视频总时长推算）."""
    if not descriptions or total_frames == 0:
        return descriptions

    for desc in descriptions:
        frame_num = desc.get("frame", 0)
        if total_frames > 1:
            desc["time_seconds"] = round(frame_num / total_frames * duration, 1)
        else:
            desc["time_seconds"] = 0.0

    return descriptions


def _merge_silence_issues(quality_issues: list[dict], silences: list[dict]):
    """确保代码侧检测的静音问题被合并到 quality_issues 中."""
    for s in silences:
        dur = s.get("duration", 0)
        if dur >= 2.0:
            # 检查是否已有相近位置的 issue
            exists = any(
                abs(iss.get("start", 0) - s["start"]) < 0.5
                for iss in quality_issues
            )
            if not exists:
                quality_issues.append({
                    "start": s["start"],
                    "end": s["end"],
                    "issue_type": "silence",
                    "severity": "high" if dur > 3.0 else "medium",
                    "detail": f"静音 {dur:.1f}秒",
                })


def _build_fallback_summary(transcript: list[dict], duration: float,
                            scenes: list[dict]) -> str:
    """LLM 不可用时的回退摘要."""
    if not transcript:
        return f"视频时长 {duration:.1f} 秒，共 {len(scenes)} 个场景。（无法获取语音内容）"

    # 取前5句和后3句作为概览
    first_texts = [t["text"] for t in transcript[:5]]
    last_texts = [t["text"] for t in transcript[-3:]]
    preview = " ".join(first_texts)[:200]
    ending = " ".join(last_texts)[:100]
    return f"视频时长 {duration:.1f} 秒，{len(scenes)} 个场景。开头: {preview}... 结尾: {ending}"
