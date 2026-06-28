"""FastAPI 路由 — REST API."""

from __future__ import annotations

import uuid
import threading
import subprocess
import platform
import shutil
import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from apex_cut.config import OUTPUT_DIR, DATA_DIR, set_runtime_keys, get_config_summary, save_config_to_env, get_providers_for_frontend

MATERIALS_DIR = DATA_DIR / "materials"
MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
from apex_cut.workflow import create_workflow
from apex_cut.sse import push_event, cleanup_queue, set_progress_callback, set_progress_overwrite_callback, set_status_callback, emit_progress, emit_progress_overwrite
from apex_cut.config import get_gpu_info_cached
from apex_cut.cache import delete_cache, rename_cache


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class CreateTaskRequest(BaseModel):
    video_path: str
    user_requirement: str
    output_name: str = ""
    content_type: str | None = None
    target_duration: float | None = None
    target_aspect_ratio: str | None = None
    # ── ROI 配置（v2 新增）──
    roi_config: list[dict] = []
    # ── 文本模型设置（独立）──
    text_provider: str = "deepseek"
    text_api_key: str = ""
    text_api_base: str = ""           # 自定义 Base URL（为空则用内置默认）
    text_model: str = ""
    # ── 视觉模型设置（独立，可选）──
    vision_provider: str = "zhipu"
    vision_api_key: str = ""
    vision_api_base: str = ""         # 自定义 Base URL
    vision_model: str = ""
    # 高级设置
    frame_interval: float = 0      # 0 = 自动
    max_vision_frames: int = 0     # 0 = 不限制
    # ── Director 预览确认后传入（跳过 Director）──
    director_confirmed: bool = False
    confirmed_content_type: str = ""
    confirmed_edit_style: str = ""
    confirmed_editing_notes: str = ""


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: str
    error: str | None


class AnalysisData(BaseModel):
    frame_labels: list[dict] = []


class TaskResult(BaseModel):
    task_id: str
    final_output: str | None
    analysis: AnalysisData | None = None


class DirectorPreviewRequest(BaseModel):
    video_path: str
    user_requirement: str
    content_type: str | None = None
    target_duration: float | None = None
    target_aspect_ratio: str | None = None
    text_provider: str = "deepseek"
    text_api_key: str = ""
    text_model: str = ""
    # ── ROI 配置（v2 可选，Director 预览不必须）──
    roi_config: list[dict] = []


class DirectorPreviewResponse(BaseModel):
    success: bool
    content_type: str = ""
    content_type_name: str = ""
    edit_style: str = ""
    editing_notes: str = ""
    plan_summary: str = ""
    error: str = ""


class RenameMaterialRequest(BaseModel):
    new_name: str

class ValidatePathRequest(BaseModel):
    path: str

class SaveConfigRequest(BaseModel):
    """保存/测试 API 配置的请求体（Base URL 不暴露给前端，统一走 .env）."""
    llm_provider: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    vision_provider: str = ""
    zhipu_api_key: str = ""
    zhipu_model: str = ""
    qwen_api_key: str = ""
    qwen_text_model: str = ""
    qwen_vision_model: str = ""
    anthropic_api_key: str = ""


# ═══════════════════════════════════════════════════════════
# 任务管理（内存存储，重启即清空）
# ═══════════════════════════════════════════════════════════

_tasks: dict[str, dict] = {}


def _preflight_check(req: CreateTaskRequest) -> bool:
    """快速预检 API Key 是否可用（发送最小请求，5 秒超时）.

    优先使用前端传入的运行时 Key，为空时回退到 .env 已保存的 Key.
    """
    from apex_cut.config import create_llm, settings as app_settings
    from langchain_core.messages import HumanMessage

    provider = req.text_provider or "deepseek"
    api_key = (req.text_api_key or "").strip()

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
        from apex_cut.errors import is_critical_api_error
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
    set_runtime_keys(vision_key=req.vision_api_key, vision_provider=req.vision_provider, vision_model=req.vision_model)

    def _push(progress, log="", **extra):
        """推送 SSE 事件 + 更新 tasks 字典."""
        _tasks[task_id]["progress"] = progress
        _tasks[task_id].update(extra)
        payload = {
            "status": _tasks[task_id]["status"],
            "progress": progress,
            "error": _tasks[task_id].get("error"),
        }
        if log:
            payload["log"] = log
        push_event(task_id, payload)

    def _log(msg):
        """仅推送一条日志（不改变进度条文字）."""
        push_event(task_id, {"log": msg})

    def _log_overwrite(msg):
        """推送覆盖式日志（前端替换末行而非追加）."""
        push_event(task_id, {"log": msg, "overwrite": True})

    def _status(msg):
        """更新前端进度条状态文字 + 覆盖式日志（每轮替换上一条）."""
        _tasks[task_id]["progress"] = msg
        push_event(task_id, {"progress": msg, "log": msg, "overwrite": True})

    # 设置全局回调，让 Agent 内部也能推送日志到前端
    set_progress_callback(_log)
    set_progress_overwrite_callback(_log_overwrite)
    set_status_callback(_status)

    try:
        workflow = create_workflow()
        initial_state = {
            "video_path": req.video_path,
            "user_requirement": req.user_requirement,
            "output_name": req.output_name,
            "content_type": req.content_type or req.confirmed_content_type,
            "target_duration": req.target_duration,
            "target_aspect_ratio": req.target_aspect_ratio,
            "output_dir": out_dir,
            # ── ROI 配置（v2）──
            "roi_config": req.roi_config or [],
            # 运行时 Key（仅存于 State，不落盘）
            "runtime_llm_provider": req.text_provider,
            "runtime_api_key": req.text_api_key,
            "runtime_api_base": req.text_api_base or "",
            "runtime_vision_key": req.vision_api_key,
            "runtime_vision_provider": req.vision_provider,
            "runtime_vision_api_base": req.vision_api_base or "",
            "runtime_text_model": req.text_model,
            "runtime_vision_model": req.vision_model,
            # 高级设置（前端传入）
            "frame_interval": req.frame_interval,
            "max_vision_frames": req.max_vision_frames,
            # Director 预览确认（跳过 Director）
            "director_plan_confirmed": req.director_confirmed,
        }
        # 计算 ROI 哈希（缓存匹配用）
        if req.roi_config:
            from apex_cut.roi_types import hash_roi_config, roi_config_from_list
            rois = roi_config_from_list(req.roi_config)
            initial_state["roi_hash"] = hash_roi_config(rois)
        if req.director_confirmed:
            initial_state.update({
                "edit_style": req.confirmed_edit_style,
                "editing_notes": req.confirmed_editing_notes,
            })

        draft_output = ""  # 跨节点追踪 editor 产出的文件路径
        analysis_data = {}  # 跨节点追踪分析结果

        # 推送 GPU 状态
        gpu_info = get_gpu_info_cached()
        gpu_summary = gpu_info.get("summary", "CPU 模式")
        if gpu_summary == "CPU 模式":
            _log(f"  ️  GPU: 未检测到 — 全程 CPU 处理")
        else:
            _log(f"   GPU: {gpu_summary}")
        _push(" 开始处理", log="━━━  导演 Agent 解析需求 ━━━")

        for event in workflow.stream(initial_state):
            node_name = list(event.keys())[0]
            node_data = event[node_name]

            if node_name == "director":
                style = node_data.get("edit_style", "")
                dur = node_data.get("target_duration")
                summary = node_data.get("director_plan_summary", "")[:120]
                dur_str = f"{dur}s" if dur else "未指定"
                _push(f"导演: {summary[:40] or '需求解析完成'}",
                      log=f" 剪辑风格: {style or '智能判断'}  |  目标时长: {dur_str}")

            elif node_name == "loader":
                # 缓存加载 — 跳过分析，直接进入剪辑
                fl = node_data.get("frame_labels", [])

                analysis_data = {
                    "frame_labels": fl,
                }
                _tasks[task_id]["analysis"] = analysis_data

                combat = sum(1 for f in fl if f.get("has_combat"))
                _push(f" 缓存命中: {len(fl)}帧标签",
                      log=f"━━━  缓存加载 — 跳过视频分析 ━━━")
                _log(f"   全部数据从侧挂缓存加载")
                _log(f"   帧标签: {len(fl)} 帧 (战斗={combat})")

            elif node_name == "analyzer":
                fl = node_data.get("frame_labels", [])

                analysis_data = {
                    "frame_labels": fl,
                }
                _tasks[task_id]["analysis"] = analysis_data

                combat = sum(1 for f in fl if f.get("has_combat"))
                _push(f"分析完成: {len(fl)}帧标签",
                      log=f"━━━  分析 Agent 完成 ━━━")
                _log(f"   帧标签: {len(fl)} 帧 (战斗={combat})")

            elif node_name == "editor":
                plan = node_data.get("edit_plan", [])
                final_out = node_data.get("final_output", "")

                if final_out:
                    draft_output = final_out
                    _tasks[task_id]["final_output"] = final_out
                    manifest_path = node_data.get("manifest_path", "")
                    if manifest_path:
                        _tasks[task_id]["manifest_path"] = manifest_path
                    _push(f"剪辑完成",
                          log=f"━━━  剪辑 Agent 执行裁剪 ━━━")
                    import os as _os
                    if _os.path.exists(final_out):
                        size_mb = _os.path.getsize(final_out) / 1048576
                        _log(f"   成品 ({len(plan)} 段合并): {Path(final_out).name} ({size_mb:.1f}MB)")

        _push(" 全部完成", log="━━━  剪辑任务完成 ━━━", status="done")

    except Exception as e:
        from apex_cut.errors import CriticalAPIError
        if isinstance(e, CriticalAPIError):
            _push(f" API 错误 ({e.status_code}): {e}", status="failed", error=str(e))
        else:
            _push(f"失败: {str(e)[:200]}", status="failed", error=f"运行异常: {str(e)[:500]}")
    finally:
        set_progress_callback(None)
        set_progress_overwrite_callback(None)
        set_status_callback(None)
        # 清理临时文件
        _cleanup_temp_files(out_dir)


# ═══════════════════════════════════════════════════════════
# 路由注册
# ═══════════════════════════════════════════════════════════

def _cleanup_temp_files(task_out_dir: str):
    """清理任务产生的临时文件（帧图片等）."""
    task_dir = Path(task_out_dir)
    if not task_dir.exists():
        return
    # 抽帧图片
    frames_dir = task_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    # 临时裁剪目录
    temp_trim = task_dir / "temp_trim"
    if temp_trim.exists():
        shutil.rmtree(temp_trim, ignore_errors=True)


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

    # ── Provider 元数据（供前端动态渲染）──

    @app.get("/api/providers")
    async def get_providers():
        """返回所有支持的 AI 平台及其文本/视觉模型列表."""
        return {"success": True, "providers": get_providers_for_frontend()}

    # ── ROI 类型预设 ──

    @app.get("/api/roi-types")
    async def get_roi_types():
        """返回所有可选的 ROI 类型预设（供前端渲染选择列表）."""
        from apex_cut.roi_types import ROI_TYPES
        return {
            "success": True,
            "types": [
                {"id": t.id, "name": t.name, "icon": t.icon, "instruction": t.instruction}
                for t in ROI_TYPES
            ],
        }

    # ── 配置持久化 ──

    @app.get("/api/config")
    async def get_config():
        """获取已保存的 API 配置（Key 已遮盖）."""
        return {"success": True, "config": get_config_summary(), "gpu": get_gpu_info_cached()}

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
        from apex_cut.config import create_llm, settings as app_settings
        from langchain_core.messages import HumanMessage

        provider = req.llm_provider or "deepseek"
        api_key = ""
        api_base = ""

        # 根据提供商获取对应的 key 和 base_url
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
        else:
            # 自定义 provider — 从 SavedConfigRequest 的扩展字段取
            api_key = getattr(req, 'deepseek_api_key', '')  # 复用字段传 key
            api_base = getattr(req, 'deepseek_api_key', '') and app_settings.deepseek_base_url

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
                "message": f" {provider.upper()} 连接成功",
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

    @app.post("/api/validate-path")
    async def validate_path(req: ValidatePathRequest):
        """验证本地视频文件路径是否可用（不拷贝，直接引用原文件）."""
        p = Path(req.path.strip())
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"文件不存在: {req.path}")
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"路径不是文件: {req.path}")

        ext = p.suffix.lower()
        allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".ts"}
        if ext not in allowed:
            raise HTTPException(status_code=400,
                detail=f"不支持的视频格式: {ext}，支持: {', '.join(sorted(allowed))}")

        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"[路径验证]  {req.path} ({size_mb:.0f}MB)")
        return {
            "success": True,
            "video_path": str(p.resolve()),
            "filename": p.name,
            "size": p.stat().st_size,
        }

    @app.post("/api/upload")
    async def upload_video(file: UploadFile = File(...)):
        """上传视频文件到素材库，流式写入，返回文件路径."""
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        # 只允许视频格式
        ext = Path(file.filename).suffix.lower()
        allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".ts"}
        if ext not in allowed:
            raise HTTPException(status_code=400,
                detail=f"不支持的视频格式: {ext}，支持: {', '.join(sorted(allowed))}")

        # 保存到素材库，保留原始文件名（加 UUID 防冲突）
        stem = Path(file.filename).stem
        safe_name = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
        file_path = MATERIALS_DIR / safe_name

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

    @app.get("/api/materials")
    async def list_materials():
        """列出素材库中所有已上传的视频."""
        materials = []
        if MATERIALS_DIR.exists():
            for p in sorted(MATERIALS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if not p.is_file():
                    continue
                ext = p.suffix.lower()
                allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".ts"}
                if ext not in allowed:
                    continue
                st = p.stat()
                materials.append({
                    "path": str(p.resolve()),
                    "filename": p.name,
                    "size_mb": round(st.st_size / (1024 * 1024), 1),
                    "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        return {"success": True, "materials": materials}

    @app.get("/api/materials/stream/{filename}")
    async def stream_material(filename: str):
        """流式播放素材库视频（支持 Range 请求，可拖拽进度条）."""
        file_path = MATERIALS_DIR / filename
        try:
            file_path = file_path.resolve()
            MATERIALS_DIR.resolve()
            if not str(file_path).startswith(str(MATERIALS_DIR.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        # 根据扩展名映射 MIME type
        ext = file_path.suffix.lower()
        mime_map = {
            ".mp4": "video/mp4", ".mov": "video/quicktime",
            ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
            ".webm": "video/webm", ".flv": "video/x-flv",
            ".wmv": "video/x-ms-wmv", ".ts": "video/mp2t",
        }
        return FileResponse(
            path=str(file_path),
            media_type=mime_map.get(ext, "video/mp4"),
            filename=filename,
        )

    @app.delete("/api/materials/{filename:path}")
    async def delete_material(filename: str):
        """从素材库删除指定视频."""
        file_path = MATERIALS_DIR / filename
        # 安全检查：确保路径在 MATERIALS_DIR 下
        try:
            file_path = file_path.resolve()
            MATERIALS_DIR.resolve()
            if not str(file_path).startswith(str(MATERIALS_DIR.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        # 同步删除侧挂缓存
        delete_cache(str(file_path))
        file_path.unlink()
        return {"success": True}

    @app.post("/api/materials/{filename:path}/rename")
    async def rename_material(filename: str, req: RenameMaterialRequest):
        """重命名素材库中的视频，同步重命名侧挂缓存目录."""
        file_path = MATERIALS_DIR / filename
        # 安全检查
        try:
            file_path = file_path.resolve()
            MATERIALS_DIR.resolve()
            if not str(file_path).startswith(str(MATERIALS_DIR.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        new_name = req.new_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="新名称不能为空")

        # 保留原始扩展名
        old_suffix = file_path.suffix
        if not new_name.lower().endswith(old_suffix.lower()):
            new_name = new_name + old_suffix

        new_path = file_path.parent / new_name
        if new_path.exists() and new_path != file_path:
            raise HTTPException(status_code=409, detail=f"文件已存在: {new_name}")

        old_path_str = str(file_path)
        new_path_str = str(new_path)

        # 先重命名缓存目录（更新 meta.json 中的 video_path）
        rename_cache(old_path_str, new_path_str)

        # 再重命名视频文件
        file_path.rename(new_path)

        return {
            "success": True,
            "old_name": filename,
            "new_name": new_name,
            "new_path": new_path_str,
        }

    @app.post("/api/director/preview", response_model=DirectorPreviewResponse)
    async def director_preview(req: DirectorPreviewRequest):
        """仅运行 Director Agent，返回方案供用户确认."""
        if not Path(req.video_path).exists():
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")

        # 构建 Director 所需的最小 state（文本 Key 通过 state 传递）
        state = {
            "video_path": req.video_path,
            "user_requirement": req.user_requirement,
            "content_type": req.content_type or "auto",
            "target_duration": req.target_duration,
            "target_aspect_ratio": req.target_aspect_ratio,
            "runtime_llm_provider": req.text_provider,
            "runtime_api_key": req.text_api_key,
            "runtime_api_base": "",
            "runtime_text_model": req.text_model,
        }

        try:
            from apex_cut.agents.director import director_node
            result = director_node(state)

            if result.get("error"):
                return DirectorPreviewResponse(success=False, error=result["error"])

            return DirectorPreviewResponse(
                success=True,
                content_type=result.get("content_type", ""),
                content_type_name=result.get("content_type_name", ""),
                edit_style=result.get("edit_style", ""),
                editing_notes=result.get("editing_notes", ""),
                plan_summary=result.get("plan_summary", ""),
            )
        except Exception as e:
            return DirectorPreviewResponse(success=False, error=str(e)[:500])

    @app.post("/api/tasks/create", response_model=TaskStatus)
    async def create_task(req: CreateTaskRequest):
        """提交一个新的视频剪辑任务."""
        if not Path(req.video_path).exists():
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")

        # 检查是否有可用的 API Key（运行时传入 或 .env 已保存）
        from apex_cut.config import settings as app_settings
        has_runtime_key = bool(req.text_api_key.strip())
        has_saved_key = bool(
            (req.text_provider == "deepseek" and app_settings.deepseek_api_key) or
            (req.text_provider == "openai" and app_settings.openai_api_key) or
            (req.text_provider == "qwen" and app_settings.qwen_api_key) or
            (req.text_provider == "anthropic" and app_settings.anthropic_api_key)
        )
        if not has_runtime_key and not has_saved_key:
            raise HTTPException(status_code=400,
                detail=f"API Key 不能为空（请在 .env 中配置 {req.text_provider.upper()}_API_KEY 或在前端填写）")

        task_id = str(uuid.uuid4())[:8]
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": "排队中...",
            "error": None,
            "final_output": None,
            "analysis": None,
        }

        # 预检：快速验证 API Key 是否可用（1 次最小调用）
        if not _preflight_check(req):
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"] = "API Key 预检失败：无法连接到 LLM 服务，请检查 Key 和网络"
            _tasks[task_id]["progress"] = " API Key 验证失败"
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

    @app.get("/api/tasks/{task_id}/stream")
    async def stream_task_status(task_id: str, request: Request):
        """SSE 实时推送任务状态（替代轮询）."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        from apex_cut.sse import event_stream

        async def generate():
            async for event in event_stream(task_id):
                if await request.is_disconnected():
                    break
                yield event
            # 任务结束后发送最终状态
            if task_id in _tasks:
                import json
                yield f"data: {json.dumps(_tasks[task_id], ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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
            analysis=analysis,
        )

    @app.get("/api/tasks/{task_id}/stream")
    async def stream_result(task_id: str, request: Request):
        """流式播放剪辑成品（支持 Range 请求，可拖拽进度条）."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        task = _tasks[task_id]
        output_path = task.get("final_output", "")
        if not output_path or not Path(output_path).exists():
            raise HTTPException(status_code=404, detail="成品文件不存在")

        file_path = Path(output_path).resolve()
        file_size = file_path.stat().st_size

        range_header = request.headers.get("range")
        if range_header:
            start_str = range_header.replace("bytes=", "").split("-")[0]
            start = int(start_str) if start_str else 0
            end = min(start + 1048576 * 10, file_size - 1)  # 10MB chunk
            with open(file_path, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            return StreamingResponse(
                iter([data]),
                status_code=206,
                media_type="video/mp4",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(data)),
                },
            )

        return FileResponse(
            path=str(file_path),
            media_type="video/mp4",
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


    @app.post("/api/tasks/open-material-folder")
    async def open_material_folder(req: Request):
        """在文件管理器中打开并定位到素材文件."""
        import json as _json
        body = await req.json()
        path = body.get("path", "")
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        abs_path = str(Path(path).resolve())
        try:
            import subprocess as _sp
            import platform as _pf
            system = _pf.system()
            if system == "Windows":
                _sp.Popen(["explorer", "/select,", abs_path])
            elif system == "Darwin":
                _sp.Popen(["open", "-R", abs_path])
            else:
                _sp.Popen(["xdg-open", str(Path(path).parent)])
            return {"success": True, "path": abs_path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"无法打开文件夹: {e}")

    @app.post("/api/tasks/{task_id}/open-folder")
    async def open_result_folder(task_id: str):
        """在文件管理器中打开并定位到成品视频文件."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        task = _tasks[task_id]
        output_path = task.get("final_output", "")
        if not output_path or not Path(output_path).exists():
            raise HTTPException(status_code=404, detail="成品文件不存在")

        abs_path = str(Path(output_path).resolve())
        try:
            system = platform.system()
            if system == "Windows":
                # explorer /select 会打开文件夹并选中文件
                subprocess.Popen(["explorer", "/select,", abs_path])
            elif system == "Darwin":
                subprocess.Popen(["open", "-R", abs_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", str(Path(output_path).parent)])
            return {"success": True, "path": abs_path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"无法打开文件夹: {e}")

    class MergeRequest(BaseModel):
        clip_order: list[int]  # 片段索引列表，如 [2, 0, 1, 3]

    @app.get("/api/tasks/{task_id}/clips/{filename}")
    async def stream_clip(task_id: str, filename: str):
        """流式播放单个片段文件."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        clips_dir = OUTPUT_DIR / task_id / "clips"
        file_path = clips_dir / filename
        try:
            file_path = file_path.resolve()
            clips_dir.resolve()
            if not str(file_path).startswith(str(clips_dir.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="片段文件不存在")

        ext = file_path.suffix.lower()
        mime_map = {
            ".mp4": "video/mp4", ".mov": "video/quicktime",
            ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
            ".webm": "video/webm", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".png": "image/png",
        }
        return FileResponse(
            path=str(file_path),
            media_type=mime_map.get(ext, "video/mp4"),
            filename=filename,
        )

    @app.get("/api/tasks/{task_id}/thumbs/{filename}")
    async def stream_thumb(task_id: str, filename: str):
        """获取片段缩略图."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        thumbs_dir = OUTPUT_DIR / task_id / "clips" / "thumbs"
        file_path = thumbs_dir / filename
        try:
            file_path = file_path.resolve()
            thumbs_dir.resolve()
            if not str(file_path).startswith(str(thumbs_dir.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="缩略图不存在")

        return FileResponse(
            path=str(file_path),
            media_type="image/jpeg",
            filename=filename,
        )

    @app.get("/api/tasks/{task_id}/manifest")
    async def get_task_manifest(task_id: str):
        """获取剪辑 manifest（片段列表元数据）."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        task = _tasks[task_id]
        manifest_path = task.get("manifest_path", "")
        if manifest_path and Path(manifest_path).exists():
            import json
            return json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        # 回退：从 clips 目录构造完整 manifest（含 start/end/events 等前端必需字段）
        out_dir = OUTPUT_DIR / task_id
        clips_dir = out_dir / "clips"
        thumbs_dir = clips_dir / "thumbs"
        clips = []
        if clips_dir.exists():
            for f in sorted(clips_dir.glob("clip_*.mp4")):
                # 从文件名解析 start/end: clip_001_30s-45s.mp4
                import re as _re
                seg_match = _re.search(r'(\d+)s-(\d+)s', f.name)
                start = float(seg_match.group(1)) if seg_match else 0
                end = float(seg_match.group(2)) if seg_match else 0
                idx_match = _re.search(r'clip_(\d+)', f.name)
                idx = int(idx_match.group(1)) if idx_match else 0
                thumb_name = f"thumb_{idx:03d}.jpg"
                thumb = thumb_name if (thumbs_dir / thumb_name).exists() else ""
                clips.append({
                    "index": idx,
                    "file": f.name,
                    "path": str(f.resolve()),
                    "thumb": thumb,
                    "start": start,
                    "end": end,
                    "reason": "",
                    "score": 0,
                    "events": [],
                })

        return {
            "task_id": task_id,
            "clips": clips,
            "merged_output": task.get("final_output", ""),
        }

    @app.post("/api/tasks/{task_id}/merge")
    async def merge_clips(task_id: str, req: MergeRequest):
        """按指定顺序拼接片段文件."""
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="任务不存在")

        out_dir = OUTPUT_DIR / task_id
        clips_dir = out_dir / "clips"

        # 读取 manifest 获取文件映射
        manifest_path = out_dir / "edit_manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="manifest 不存在")

        import json as _json
        manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_clips = manifest.get("clips", [])

        # 按请求顺序排列文件
        ordered_files = []
        for idx in req.clip_order:
            clip_info = manifest_clips[idx] if idx < len(manifest_clips) else None
            if clip_info:
                fpath = clips_dir / clip_info["file"]
                if fpath.exists():
                    ordered_files.append(str(fpath.resolve()))

        if not ordered_files:
            raise HTTPException(status_code=400, detail="没有找到有效的片段文件")

        merged_output = str(out_dir / f"merged_custom.mp4")
        from apex_cut.tools.video_tools import get_ffmpeg
        result = get_ffmpeg().concat(ordered_files, merged_output)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "拼接失败"))

        # 更新 task 的 final_output
        _tasks[task_id]["final_output"] = merged_output

        return {
            "success": True,
            "output_path": merged_output,
            "files_merged": len(ordered_files),
            "order": req.clip_order,
        }

    @app.get("/api/results")
    async def get_results():
        """列出所有已处理的视频结果（从 results 目录，按时间倒序）."""
        results = []
        results_dir = OUTPUT_DIR / "results"
        if results_dir.exists():
            for mp4 in sorted(results_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                st = mp4.stat()
                results.append({
                    "filename": mp4.name,
                    "size_mb": round(st.st_size / 1048576, 1),
                    "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "url": f"/api/results/{mp4.name}",
                })
        return {"success": True, "results": results}

    @app.get("/api/results/{filename}")
    async def serve_result(filename: str):
        """直接访问 results 目录下的文件."""
        file_path = OUTPUT_DIR / "results" / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path=str(file_path), media_type="video/mp4", filename=filename)

    @app.get("/api/results/stream/{filename}")
    async def stream_result(filename: str):
        """流式播放结果视频（支持 Range 请求，可拖拽进度条）."""
        results_dir = OUTPUT_DIR / "results"
        file_path = results_dir / filename
        try:
            file_path = file_path.resolve()
            results_dir.resolve()
            if not str(file_path).startswith(str(results_dir.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(
            path=str(file_path),
            media_type="video/mp4",
            filename=filename,
            content_disposition_type="inline",
        )

    @app.get("/api/output/{filename}")
    async def serve_output(filename: str):
        """直接访问 OUTPUT_DIR 下的文件."""
        file_path = OUTPUT_DIR / filename
        try:
            file_path = file_path.resolve()
            OUTPUT_DIR.resolve()
            if not str(file_path).startswith(str(OUTPUT_DIR.resolve())):
                raise HTTPException(status_code=403, detail="路径非法")
        except Exception:
            raise HTTPException(status_code=400, detail="文件名无效")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path=str(file_path), media_type="video/mp4", filename=filename)

    # ── SPA fallback (React Router) — 必须放在所有 API 路由之后 ──
    if react_dist.exists():
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            """非 API 路径回退到 React SPA."""
            index_path = react_dist / "index.html"
            if index_path.exists():
                return HTMLResponse(index_path.read_text(encoding="utf-8"))
            raise HTTPException(status_code=404)
