#!/usr/bin/env python3
"""AutoCut Agent — 启动入口.

用法:
    # 启动 FastAPI 服务
    python main.py serve --port 8000

    # 命令行直接运行一个剪辑任务
    python main.py run --video sample.mp4 --requirement "剪成3分钟精华版"

    # 查看版本
    python main.py --version
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def cmd_serve(args):
    """启动 FastAPI 服务."""
    import uvicorn
    from apex_cut.api.routes import register_routes
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.requests import Request

    # 大文件上传临时目录改到项目 data 目录（C 盘空间不足 9GB）
    import tempfile
    from apex_cut.config import DATA_DIR
    _upload_tmp = DATA_DIR / "tmp"
    _upload_tmp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(_upload_tmp)

    # Starlette 1.x: Request.form() 默认 max_part_size=1MB，提高上限
    _original_get_form = Request._get_form

    async def _patched_get_form(self, *, max_files=1000, max_fields=1000, max_part_size=1024 * 1024):
        max_part_size = max(max_part_size, 20 * 1024 * 1024 * 1024)
        return await _original_get_form(self, max_files=max_files, max_fields=max_fields, max_part_size=max_part_size)

    Request._get_form = _patched_get_form

    app = FastAPI(
        title="AutoCut Agent",
        description="基于 LangGraph 的智能视频剪辑 AI Agent",
        version="0.1.0",
    )

    # CORS — 允许前端跨域请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=600,
    )

    register_routes(app)

    print(f"\n AutoCut Agent API 启动中...")
    print(f"   地址: http://localhost:{args.port}")
    print(f"   文档: http://localhost:{args.port}/docs\n")

    uvicorn.run(app, host="0.0.0.0", port=args.port, loop="asyncio",
                timeout_keep_alive=300)


def cmd_run(args):
    """命令行直接运行剪辑任务."""
    from apex_cut.workflow import run_editing_task

    print("\n AutoCut Agent — 命令行模式\n")
    print(f"   视频: {args.video}")
    print(f"   需求: {args.requirement}")
    if args.duration:
        print(f"   目标时长: {args.duration}s")
    if args.aspect:
        print(f"   目标画幅: {args.aspect}")
    print()

    result = run_editing_task(
        video_path=args.video,
        user_requirement=args.requirement,
        target_duration=args.duration,
        target_aspect_ratio=args.aspect,
    )

    print("\n" + "=" * 60)
    print(" 剪辑结果")
    print("=" * 60)
    print(f"  审核评分: {result.get('review_score', 'N/A')}/100")
    print(f"  审核通过: {' 是' if result.get('review_approved') else ' 否'}")
    print(f"  审核轮次: {result.get('review_round', 0)}")
    if result.get("review_issues"):
        print("  问题列表:")
        for issue in result["review_issues"]:
            print(f"    - {issue}")
    if result.get("final_output"):
        print(f"  输出文件: {result['final_output']}")
    if result.get("error"):
        print(f"   错误: {result['error']}")
    print("=" * 60 + "\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AutoCut Agent — 基于 LangGraph 的智能视频剪辑 AI Agent",
    )
    parser.add_argument("--version", action="store_true", help="显示版本号")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # serve 子命令
    serve_parser = subparsers.add_parser("serve", help="启动 FastAPI 服务")
    serve_parser.add_argument("--port", type=int, default=8000, help="服务端口 (默认: 8000)")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="命令行直接运行剪辑任务")
    run_parser.add_argument("--video", required=True, help="输入视频文件路径")
    run_parser.add_argument("--requirement", required=True, help="剪辑需求描述")
    run_parser.add_argument("--duration", type=float, default=None, help="目标时长（秒）")
    run_parser.add_argument("--aspect", type=str, default=None, help="目标画幅（如 9:16）")

    args = parser.parse_args()

    if args.version:
        from apex_cut import __version__
        print(f"AutoCut Agent v{__version__}")
        return

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
