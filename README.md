# ApexCut Agent

> 输入 Apex Legends 游戏录像，AI 自动分析画面数据、定位战斗时刻、裁剪导出集锦。

## 这是什么

打完一局 Apex 录了 20 分钟，不想手动翻找战斗片段？ApexCut 自动帮你做：

1. 上传视频，配置 API Key
2. 视觉 AI 逐帧读取伤害数字，自动识别战斗片段
3. ±4s 前后摇裁剪，FFmpeg 合并导出成品

基于 LangGraph 多智能体编排。视觉 LLM 对比相邻帧的伤害数字变化，全权判定每帧是否有战斗发生，代码层仅做格式校验和片段裁剪。

## 功能

-  专为 Apex Legends 设计，视觉 AI 检测伤害数字变化定位战斗
-  ROI 区域框选，精准定位伤害数字区域，大幅提升准确率
- ️ 视觉 LLM 逐帧对比数字，输出结构化 `numbers` + `event`，无需 OCR
-  侧挂缓存，同一视频重跑秒级跳过分析
-  FFmpeg 自动 GPU 加速（NVENC/QSV/AMF）
-  Web UI + 命令行两种使用方式
-  支持 DeepSeek / Qwen / GLM / OpenAI / Anthropic

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
python main.py run --video sample.mp4 --requirement "剪成3分钟精华版"
```

**Web UI 模式：**

```bash
.\start.bat              # Windows 一键启动
# 后端 http://localhost:8000  |  前端 http://localhost:3000
```

## 配置

`.env` 主要选项：

```bash
LLM_PROVIDER=deepseek          # 文本 LLM：deepseek / qwen / zhipu / openai / anthropic
DEEPSEEK_API_KEY=sk-xxx

VISION_PROVIDER=zhipu          # 视觉 LLM（读取游戏画面数字）
ZHIPU_API_KEY=xxx

FFMPEG_HWACCEL=auto            # 硬件加速：auto / cuda / qsv / amf / none
```

文本和视觉模型可以分别选择不同的提供商（比如 DeepSeek 做文本 + 智谱做视觉）。

## API

后端提供 FastAPI 接口，完整文档见 `http://localhost:8000/docs`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/create` | 提交剪辑任务 |
| GET | `/api/tasks/{id}/stream` | SSE 实时进度 |
| GET | `/api/tasks/{id}/result` | 获取结果 |
| GET | `/api/tasks/{id}/video` | 流式播放成品 |
| GET | `/api/tasks/{id}/download` | 下载成品 |
| POST | `/api/upload` | 上传视频素材 |
| GET | `/api/materials` | 素材列表 |
| GET | `/api/config` | 当前配置 |
| GET | `/api/providers` | 可用模型列表 |

## 工作流

```
START → Director（解析需求）
           ├── 缓存命中 → Loader（加载缓存）→ Editor
           └── 缓存未命中 → Analyzer（视觉分析）→ Editor → END
```

- **Director** — 解析用户需求，判断内容类型
- **Analyzer** — 逐帧截图 → 视觉 LLM 读取伤害数字 → 判定战斗帧
- **Editor** — 战斗帧 ±4s 前后摇 → 合并重叠片段 → FFmpeg 裁剪导出

## 项目结构

```
apex-cut/
├── apex_cut/agents/     # Director / Analyzer / Editor
├── apex_cut/tools/      # FFmpeg 封装 + 视觉分析
├── apex_cut/api/        # FastAPI 路由
├── frontend/            # React (Vite)
├── main.py              # 启动入口
└── start.bat            # Windows 一键启动
```

## License

MIT
