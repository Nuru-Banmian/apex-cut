"""导演 Agent — 理解用户需求，拆解剪辑任务."""

from __future__ import annotations

import json
from langchain_core.messages import HumanMessage, SystemMessage

from autocut.state import VideoEditState
from autocut.config import create_llm, _extract_runtime_keys
from autocut.errors import check_and_raise


DIRECTOR_SYSTEM_PROMPT = """你是一位专业的视频剪辑导演。你的工作是根据用户的剪辑需求，制定详细的剪辑策略。

你需要从用户的需求中提取以下结构化信息，并以 JSON 格式返回：

{
    "target_duration": 数值（秒）或 null,
    "target_aspect_ratio": "16:9" / "9:16" / "1:1" / "4:3" 或 null,
    "edit_style": "快节奏" / "正式" / "温情" / "简约" / "保留原风格",
    "focus_keywords": ["关键词1", "关键词2"],
    "remove_instructions": ["要去掉的内容"],
    "keep_instructions": ["要保留的内容"],
    "subtitle_language": "zh" / "en" / "auto",
    "add_bgm": true / false,
    "bgm_mood": "energetic" / "calm" / "emotional" / "corporate" 或 null,
    "plan_summary": "用一段话总结剪辑策略"
}

如果用户没有指定某个字段，返回 null。
不要包含 JSON 之外的任何内容。"""


def director_node(state: VideoEditState) -> dict:
    """导演节点 — 解析需求，制定策略."""
    requirement = state.get("user_requirement", "")
    video_path = state.get("video_path", "")

    print(f"[🎬 导演] 收到需求: {requirement}")
    print(f"[🎬 导演] 视频路径: {video_path}")

    if not requirement.strip():
        return {
            "user_requirement": requirement,
            "target_duration": None,
            "target_aspect_ratio": None,
        }

    try:
        provider, api_key, api_base = _extract_runtime_keys(state)
        llm = create_llm(temperature=0.3, runtime_provider=provider,
                         runtime_api_key=api_key, runtime_base_url=api_base)
        response = llm.invoke([
            SystemMessage(content=DIRECTOR_SYSTEM_PROMPT),
            HumanMessage(content=f"用户的剪辑需求：{requirement}\n视频路径：{video_path}"),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0]

        plan = json.loads(content)

        print(f"[🎬 导演] 策略解析完成:")
        print(f"  目标时长: {plan.get('target_duration')}s")
        print(f"  目标画幅: {plan.get('target_aspect_ratio')}")
        print(f"  剪辑风格: {plan.get('edit_style')}")
        print(f"  需求摘要: {plan.get('plan_summary', '')[:80]}...")

        return {
            "user_requirement": json.dumps(plan, ensure_ascii=False),
            "target_duration": plan.get("target_duration"),
            "target_aspect_ratio": plan.get("target_aspect_ratio"),
            "director_plan": plan,  # 结构化计划单独存储
            "director_plan_summary": plan.get("plan_summary", ""),
            "edit_style": plan.get("edit_style", ""),
        }
    except json.JSONDecodeError as e:
        print(f"[🎬 导演] JSON 解析失败，使用原始需求: {e}")
        return {
            "user_requirement": requirement,
            "target_duration": None,
            "target_aspect_ratio": None,
        }
    except Exception as e:
        check_and_raise(e, "导演")
        print(f"[🎬 导演] LLM 调用失败: {e}")
        return {
            "user_requirement": requirement,
            "target_duration": None,
            "target_aspect_ratio": None,
        }
