"""FastAPI 路由 — REST API."""

from __future__ import annotations

import uuid
import threading
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from autocut.config import OUTPUT_DIR, DATA_DIR, set_runtime_keys, get_config_summary, save_config_to_env
from autocut.workflow import create_workflow


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class CreateTaskRequest(BaseModel):
    video_path: str
    user_requirement: str
    target_duration: float | None = None
    target_aspect_ratio: str | None = None
    # 运行时 API Key（不落盘，任务结束后即释放）
    llm_provider: str = "deepseek"
    api_key: str = ""
    vision_key: str = ""          # 视觉分析 Key
    vision_provider: str = "zhipu"  # 视觉提供商: openai / zhipu / qwen


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: str
    review_round: int
    review_score: float | None
    error: str | None


class AnalysisData(BaseModel):
    content_summary: str = ""
    content_tags: list[str] = []
    mood: str = ""
    mood_curve: list[dict] = []
    narrative_structure: dict = {}
    highlights: list[dict] = []
    quality_issues: list[dict] = []
    scene_analyses: list[dict] = []
    frame_descriptions: list[dict] = []
    transcript_segments: int = 0
    scenes_count: int = 0
    energy_peaks: int = 0


class TaskResult(BaseModel):
    task_id: str
    final_output: str | None
    review_score: float | None
    review_issues: list[str]
    analysis: AnalysisData | None = None


class SaveConfigRequest(BaseModel):
    """保存/测试 API 配置的请求体（Base URL 不暴露给前端，统一走 .env）."""
    llm_provider: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    vision_provider: str = ""
    zhipu_api_key: str = ""
    qwen_api_key: str = ""
    anthropic_api_key: str = ""


# ═══════════════════════════════════════════════════════════
# 任务管理（内存存储，重启即清空）
# ═══════════════════════════════════════════════════════════

_tasks: dict[str, dict] = {}


def _preflight_check(req: CreateTaskRequest) -> bool:
    """快速预检 API Key 是否可用（发送最小请求，5 秒超时）.

    优先使用前端传入的运行时 Key，为空时回退到 .env 已保存的 Key.
    """
    from autocut.config import create_llm, settings as app_settings
    from langchain_core.messages import HumanMessage

    provider = req.llm_provider or "deepseek"
    api_key = (req.api_key or "").strip()

    # 运行时 Key 为空 → 回退到 .env 中已保存的 Key
    if not api_key:
        if provider == "deepseek":
            api_key = app_settings.deepseek_api_key
        elif provider == "openai":
            api_key = app_settings.openai_api_key
        elif provider == "qwen":
            api_key = app_settings.qwen_api_key
        elif provider == "anthropic":
            api_key = app_settings.anthropic_api_key

    if not api_key:
        print(f"[预检] 无可用 API Key ({provider})")
        return False

    try:
        llm = create_llm(
            temperature=0.0,
            runtime_provider=provider,
            runtime_api_key=api_key,
            runtime_base_url="",  # 走 settings 默认值
        )
        # 发送最小测试消息验证连通性
        resp = llm.invoke([HumanMessage(content="hi")])
        return bool(resp)
    except Exception as e:
        from autocut.errors import is_critical_api_error
        is_critical, _, hint = is_critical_api_error(e)
        if is_critical:
            print(f"[预检] API Key 验证失败 ({provider}): {hint}")
        else:
            print(f"[预检] API Key 验证异常 ({provider}): {e}")
        return False


def _run_task(task_id: str, req: CreateTaskRequest):
    """在后台线程中运行剪辑任务."""
    out_dir = str(OUTPUT_DIR / task_id)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["progress"] = "初始化..."

    # 将视觉 Key + 提供商写入线程变量，供 describe_frames 工具使用
    set_runtime_keys(vision_key=req.vision_key, vision_provider=req.vision_provider)

    try:
        workflow = create_workflow()
        initial_state = {
            "video_path": req.video_path,
            "user_requirement": req.user_requirement,
            "target_duration": req.target_duration,
            "target_aspect_ratio": req.target_aspect_ratio,
            "output_dir": out_dir,
            "review_round": 0,
            # 运行时 Key（仅存于 State，不落盘）
            "runtime_llm_provider": req.llm_provider,
            "runtime_api_key": req.api_key,
            "runtime_api_base": "",  # base_url 统一走 .env 配置
            "runtime_vision_key": req.vision_key,
            "runtime_vision_provider": req.vision_provider,
        }

        draft_output = ""  # 跨节点追踪 editor 产出的文件路径
        analysis_data = {}  # 跨节点追踪分析结果

        for event in workflow.stream(initial_state):
            node_name = list(event.keys())[0]
            node_data = event[node_name]
            _tasks[task_id]["progress"] = f"执行中: {node_name}"
            _tasks[task_id]["review_round"] = node_data.get("review_round", 0)
            if "review_score" in node_data:
                _tasks[task_id]["review_score"] = node_data["review_score"]

            # 捕获分析阶段的产出
            if node_name == "analyzer":
                analysis_data = {
                    "content_summary": node_data.get("content_summary", ""),
                    "content_tags": node_data.get("content_tags", []),
                    "mood": node_data.get("mood", ""),
                    "mood_curve": node_data.get("mood_curve", []),
                    "narrative_structure": node_data.get("narrative_structure", {}),
                    "highlights": node_data.get("highlights", []),
                    "quality_issues": node_data.get("quality_issues", []),
                    "scene_analyses": node_data.get("scene_analyses", []),
                    "frame_descriptions": node_data.get("frame_descriptions", []),
                    "transcript_segments": len(node_data.get("transcript", [])),
                    "scenes_count": len(node_data.get("scenes", [])),
                    "energy_peaks": len(node_data.get("energy_peaks", [])),
                }
                _tasks[task_id]["analysis"] = analysis_data

            # editor 产出 draft_output，记录下来
            if "draft_output" in node_data and node_data["draft_output"]:
                draft_output = node_data["draft_output"]
                _tasks[task_id]["final_output"] = draft_output

            if node_name == "reviewer":
                _tasks[task_id].update({
                    "final_output": draft_output,  # 用 editor 产出的路径
                    "review_score": node_data.get("review_score"),
                    "review_issues": node_data.get("review_issues", []),
                    "review_approved": node_data.get("review_approved", False),
                })

        _tasks[task_id]["status"] = "done"
        _tasks[task_id]["progress"] = "完成"

    except Exception as e:
        from autocut.errors import CriticalAPIError
        if isinstance(e, CriticalAPIError):
            # 关键 API 错误 — 清晰展示给用户
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["progress"] = f"❌ API 错误 ({e.status_code}): {e}"
        else:
            _tasks[task_id]["error"] = f"运行异常: {str(e)[:500]}"
            _tasks[task_id]["progress"] = f"失败: {str(e)[:200]}"
        _tasks[task_id]["status"] = "failed"


# ═══════════════════════════════════════════════════════════
# 路由注册
# ═══════════════════════════════════════════════════════════

def register_routes(app: FastAPI):
    """注册所有 API 路由."""

    # ── 静态文件（React 构建产物或旧版 HTML）──
    react_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

    if react_dist.exists() and (react_dist / "index.html").exists():
        # React 构建存在 → 挂载静态资源 + SPA 入口
        assets_dir = react_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return HTMLResponse((react_dist / "index.html").read_text(encoding="utf-8"))
    else:
        # 回退到旧版 HTML
        @app.get("/", response_class=HTMLResponse)
        async def index():
            ui_path = Path(__file__).resolve().parent.parent / "ui" / "index.html"
            if ui_path.exists():
                return HTMLResponse(ui_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>前端页面未找到</h1>", status_code=404)

    # ── 配置持久化 ──

    @app.get("/api/config")
    async def get_config():
        """获取已保存的 API 配置（Key 已遮盖）."""
        return {"success": True, "config": get_config_summary()}

    @app.post("/api/config")
    async def save_config(req: SaveConfigRequest):
        """保存 API 配置到 .env 文件，下次启动自动加载."""
        try:
            saved = save_config_to_env(req.model_dump())
            return {"success": saved, "message": "配置已保存到 .env" if saved else "无新配置需要保存"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    @app.post("/api/config/test")
    async def test_api_key(req: SaveConfigRequest):
        """测试 API Key 是否可用（发送一条最小请求验证连通性）."""
        from autocut.config import create_llm, settings as app_settings
        from langchain_core.messages import HumanMessage

        provider = req.llm_provider or "deepseek"
        api_key = ""

        # 根据提供商获取对应的 key，base_url 统一走 .env 配置
        if provider == "deepseek":
            api_key = req.deepseek_api_key
            api_base = app_settings.deepseek_base_url
        elif provider == "openai":
            api_key = req.openai_api_key
            api_base = app_settings.openai_base_url
        elif provider == "qwen":
            api_key = req.qwen_api_key
            api_base = app_settings.qwen_base_url
        elif provider == "anthropic":
            api_key = req.anthropic_api_key
            api_base = ""

        if not api_key:
            raise HTTPException(status_code=400, detail=f"请先填写 {provider.upper()} API Key")

        try:
            llm = create_llm(
                temperature=0.0,
                runtime_provider=provider,
                runtime_api_key=api_key,
                runtime_base_url=api_base,
            )
            # 发送最小测试消息（3个token足够验证连通性）
            resp = llm.invoke([HumanMessage(content="hi")], max_tokens=3)
            reply = resp.content if hasattr(resp, "content") else str(resp)

            return {
                "success": True,
                "provider": provider,
                "message": f"✅ {provider.upper()} 连接成功",
                "test_reply": reply[:50],
            }
        except Exception as e:
            error_msg = str(e)
            # 提取关键错误信息
            if "401" in error_msg or "Unauthorized" in error_msg:
                hint = "API Key 无效，请检查是否填写正确"
            elif "403" in error_msg or "Forbidden" in error_msg:
                hint = "API Key 无权限，请检查账户余额或权限"
            elif "timeout" in error_msg.lower() or "connect" in error_msg.lower():
                hint = "连接超时，请检查网络或 Base URL"
            elif "429" in error_msg:
                hint = "请求频率超限，请稍后重试"
            else:
                hint = error_msg[:200]
            return {"success": False, "error": hint, "provider": provider}

    @app.post("/api/upload")
    async def upload_video(file: UploadFile = File(...)):
        """上传视频文件到服务器，流式写入，返回文件路径."""
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        # 只允许视频格式
        ext = Path(file.filename).suffix.lower()
        allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".ts"}
        if ext not in allowed:
            raise HTTPException(status_code=400,
                detail=f"不支持的视频格式: {ext}，支持: {', '.join(sorted(allowed))}")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        file_path = DATA_DIR / f"upload_{uuid.uuid4().hex[:8]}{ext}"

        # 流式写入，避免大文件撑爆内存
        total = 0
        with open(file_path, "wb") as f:
            while chunk := await file.read(8 * 1024 * 1024):  # 8MB chunks
                f.write(chunk)
                total += len(chunk)

        return {
            "success": True,
            "video_path": str(file_path.resolve()),
            "filename": file.filename,
            "size": total,
        }

    @app.post("/api/tasks/create", response_model=TaskStatus)
    async def create_task(req: CreateTaskRequest):
        """提交一个新的视频剪辑任务."""
        if not Path(req.video_path).exists():
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")

        # 检查是否有可用的 API Key（运行时传入 或 .env 已保存）
        from autocut.config import settings as app_settings
        has_runtime_key = bool(req.api_key.strip())
        has_saved_key = bool(
            (req.llm_provider == "deepseek" and app_settings.deepseek_api_key) or
            (req.llm_provider == "openai" and app_settings.openai_api_key) or
            (req.llm_provider == "qwen" and app_settings.qwen_api_key) or
            (req.llm_provider == "anthropic" and app_settings.anthropic_api_key)
        )
        if not has_runtime_key and not has_saved_key:
            raise HTTPException(status_code=400,
                detail=f"API Key 不能为空（请在 .env 中配置 {req.llm_provider.upper()}_API_KEY 或在前端填写）")

        task_id = str(uuid.uuid4())[:8]
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": "排队中...",
            "review_round": 0,
            "review_score": None,
            "error": None,
            "final_output": None,
            "final_subtitle": None,
            "review_issues": [],
            "analysis": None,
        }

        # 预检：快速验证 API Key 是否可用（1 次最小调用）
        if not _preflight_check(req):
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"] = "API Key 预检失败：无法连接到 LLM 服务，请检查 Key 和网络"
            _tasks[task_id]["progress"] = "❌ API Key 验证失败"
            return TaskStatus(**_tasks[task_id])

        thread = threading.Thread(target=_run_task, args=(task_id, req), daemon=True)
        thread.start()

        return TaskStatus(**_tasks[task_id])

    @app.get("/api/tasks/{task_id}", response_model=TaskStatus)
    async def get_task_status(task_id: str):
        """查询任务状态."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")
        return TaskStatus(**_tasks[task_id])

    @app.get("/api/tasks/{task_id}/result", response_model=TaskResult)
    async def get_task_result(task_id: str):
        """获取剪辑成品信息（含深度分析结果）."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        task = _tasks[task_id]
        if task["status"] in ("pending", "running"):
            raise HTTPException(status_code=425, detail="任务尚未完成")

        analysis = None
        if task.get("analysis"):
            analysis = AnalysisData(**task["analysis"])

        return TaskResult(
            task_id=task_id,
            final_output=task.get("final_output"),
            review_score=task.get("review_score"),
            review_issues=task.get("review_issues", []),
            analysis=analysis,
        )

    @app.get("/api/tasks/{task_id}/download")
    async def download_result(task_id: str):
        """下载剪辑成品视频文件."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        task = _tasks[task_id]
        output_path = task.get("final_output", "")
        if not output_path or not Path(output_path).exists():
            raise HTTPException(status_code=404, detail="成品文件不存在")

        return FileResponse(
            path=output_path,
            filename=Path(output_path).name,
            media_type="video/mp4",
        )

    # ── SPA fallback (React Router) — 必须放在所有 API 路由之后 ──
    if react_dist.exists():
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            """非 API 路径回退到 React SPA."""
            index_path = react_dist / "index.html"
            if index_path.exists():
                return HTMLResponse(index_path.read_text(encoding="utf-8"))
            raise HTTPException(status_code=404)
