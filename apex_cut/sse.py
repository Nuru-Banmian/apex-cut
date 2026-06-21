"""SSE 事件流 — 替代 HTTP 轮询，实时推送任务状态."""

import asyncio
import json
import threading
from typing import Optional, Callable


# 全局事件队列：task_id → asyncio.Queue
_task_queues: dict[str, asyncio.Queue] = {}
_lock = threading.Lock()

# 全局进度回调 — 供 Agent 节点内部推送日志到 SSE
# routes.py 在启动任务前设置此回调
_progress_callback: Optional[Callable] = None
_progress_overwrite_callback: Optional[Callable] = None
_status_callback: Optional[Callable] = None


def set_progress_callback(cb: Optional[Callable]):
    """设置全局进度回调（由 routes.py 在启动任务前调用）."""
    global _progress_callback
    _progress_callback = cb


def set_progress_overwrite_callback(cb: Optional[Callable]):
    """设置覆盖式进度回调（前端替换末行而非追加）."""
    global _progress_overwrite_callback
    _progress_overwrite_callback = cb


def set_status_callback(cb: Optional[Callable]):
    """设置状态栏回调 — 更新前端进度条文字（如百分比）."""
    global _status_callback
    _status_callback = cb


def emit_progress(msg: str):
    """推送一条进度日志到 SSE（追加新行）."""
    cb = _progress_callback
    if cb:
        cb(msg)


def emit_progress_overwrite(msg: str):
    """推送一条覆盖式进度日志到 SSE（替换末行）."""
    cb = _progress_overwrite_callback
    if cb:
        cb(msg)


def emit_status(msg: str):
    """更新前端进度条状态文字（如百分比进度）."""
    cb = _status_callback
    if cb:
        cb(msg)


def get_queue(task_id: str) -> asyncio.Queue:
    """获取或创建任务的事件队列."""
    with _lock:
        if task_id not in _task_queues:
            _task_queues[task_id] = asyncio.Queue()
        return _task_queues[task_id]


def push_event(task_id: str, event: dict):
    """向任务队列推送事件（线程安全，由后台线程调用）."""
    with _lock:
        queue = _task_queues.get(task_id)
        if queue is not None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


def cleanup_queue(task_id: str):
    """任务完成后清理队列."""
    with _lock:
        _task_queues.pop(task_id, None)


async def event_stream(task_id: str):
    """SSE 生成器 — 监听任务事件并 yield SSE 格式."""
    queue = get_queue(task_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                yield f": heartbeat\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        cleanup_queue(task_id)
