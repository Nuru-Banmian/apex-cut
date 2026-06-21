# ApexCut Agent

> 输入 Apex Legends 游戏录像和一句话需求，AI 自动剪辑高光集锦。

## 这是什么

打完一局 Apex 录了 20 分钟，不想手动翻找击杀片段？ApexCut Agent 自动帮你干这件事：

1. 你上传一个视频，配置好api-key
2. AI 自动分析画面数据、定位战斗时刻、裁剪导出成品

基于 LangGraph 多智能体协作，LLM 负责理解需求，纯代码规则引擎负责确定片段边界——不会因为 AI 幻觉剪错位置。

## 功能

- 🎮 专为 Apex Legends 设计，识别击杀/助攻/伤害事件
- 🧠 LLM 翻译自然语言需求为精确剪辑参数
- 👁️ 视觉 AI 读取游戏 UI 数据，无需 OCR
- ⚡ 侧挂缓存，同一视频重跑秒级跳过分析
- 🎬 FFmpeg 自动 GPU 加速（NVENC/QSV/AMF）
- 🌐 Web UI + 命令行两种使用方式
- 🔑 支持 DeepSeek / Qwen / GLM / OpenAI / Anthropic

## 环境要求

- Python 3.11+
- FFmpeg（建议完整版，支持 GPU 编码器）
- Node.js 18+（仅 Web UI 需要）

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/Nuru-Banmian/apex-cut.git
cd apex-cut

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入至少一个 LLM 提供商的 Key

# 4. 运行
python main.py run --video sample.mp4 --requirement "保留所有击杀，快节奏2分钟"
```

**Web UI 模式：**

```bash
.\start.ps1              # Windows 一键启动
# 后端 http://localhost:8000  |  前端 http://localhost:3000
```

## 配置

`.env` 主要选项：

```bash
LLM_PROVIDER=deepseek          # 文本 LLM：deepseek / qwen / zhipu / openai / anthropic
DEEPSEEK_API_KEY=sk-xxx

VISION_PROVIDER=zhipu          # 视觉 LLM（用于读取游戏画面数据）
ZHIPU_API_KEY=xxx

FFMPEG_HWACCEL=auto            # 硬件加速：auto / cuda / qsv / amf / none
MAX_REVIEW_ROUNDS=6            # 审核修改最大轮数
```

文本和视觉模型可以分别选择不同的提供商（比如 DeepSeek 做文本 + 智谱做视觉）。

## API

后端提供 FastAPI 接口，完整文档见 `http://localhost:8000/docs`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/create` | 提交剪辑任务 |
| GET | `/api/tasks/{id}/stream` | SSE 实时进度 |
| GET | `/api/tasks/{id}/result` | 获取结果 |
| GET | `/api/tasks/{id}/download` | 下载成品 |
| POST | `/api/upload` | 上传视频素材 |
| GET | `/api/materials` | 素材列表 |
| GET | `/api/config` | 当前配置 |
| GET | `/api/providers` | 可用模型列表 |

## 项目结构

```
apex-cut/
├── apex_cut/agents/     # Director → Analyzer → Editor → Reviewer
├── apex_cut/tools/      # FFmpeg 封装 + 视觉分析
├── apex_cut/api/        # FastAPI 路由
├── frontend/            # React (Vite)
├── main.py              # 启动入口
└── start.ps1            # 一键启动脚本
```

## License

MIT
