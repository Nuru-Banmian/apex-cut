# AutoCut Agent

基于 **LangGraph** 多智能体协作的自动视频剪辑 AI Agent 后端。

## 架构

```
用户请求 → 导演 Agent → 分析 Agent → 剪辑 Agent → 审核 Agent
                            ↑                       │
                            └─── 不通过则重剪 ───────┘
```

- **导演 Agent** — 解析用户需求（目标时长、画幅、风格），制定剪辑策略
- **分析 Agent** — 语音转写、场景检测、静音识别、音频能量分析、多模态画面描述
- **剪辑 Agent** — 基于分析结果执行裁剪、拼接、字幕、转场、BGM 匹配
- **审核 Agent** — 质量评分（时长/内容/节奏/技术），不通过则反馈修改

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 3. 命令行运行

```bash
python main.py run --video sample.mp4 --requirement "剪成3分钟精华版，竖屏9:16"
```

### 4. 启动 API 服务

```bash
python main.py serve --port 8000
# 访问 http://localhost:8000/docs 查看 API 文档
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/create` | 提交剪辑任务 |
| GET | `/api/tasks/{id}` | 查询任务状态 |
| GET | `/api/tasks/{id}/result` | 获取成品信息 |
| GET | `/api/tasks/{id}/download` | 下载成品视频 |

## 项目结构

```
autocut-agent/
├── autocut/
│   ├── agents/          # Agent 节点实现
│   │   ├── director.py  #   导演 — 需求解析
│   │   ├── analyzer.py  #   分析 — 视频理解
│   │   ├── editor.py    #   剪辑 — 视频操作
│   │   └── reviewer.py  #   审核 — 质量检查
│   ├── tools/           # 工具层 (Function Calling)
│   │   ├── video_tools.py    # FFmpeg 视频操作
│   │   ├── audio_tools.py    # Whisper 语音转写 + 音频分析
│   │   ├── subtitle_tools.py # 字幕生成
│   │   └── vision_tools.py   # 多模态视觉分析
│   ├── api/             # FastAPI 路由
│   ├── state.py         # LangGraph State 定义
│   ├── workflow.py      # LangGraph 工作流编排
│   └── config.py        # 全局配置
├── main.py              # 启动入口
└── requirements.txt
```

## 技术栈

- **Agent 框架**: LangGraph + LangChain
- **LLM**: GPT-4o / Claude（多模态理解 + 剪辑决策）
- **视频处理**: FFmpeg（裁剪/拼接/字幕/转场）
- **语音转写**: Faster-Whisper
- **场景检测**: PySceneDetect
- **音频分析**: librosa + pydub
- **API**: FastAPI
