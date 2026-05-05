# SKYMIRROR 部署 README

## 1. 文档目标

这份文档面向整个 `SKYMIRROR` 项目的部署、初始化和运行，覆盖以下场景：

- 本地开发部署
- 单机命令行运行
- Docker / Docker Compose 部署
- RAG 语料准备与 Pinecone 初始化
- Dashboard 启动与验证
- 常见故障排查

如果你想先理解系统逻辑，再回来看部署细节，可先阅读 [`SKYMIRROR_PROJECT_LOGIC.md`](SKYMIRROR_PROJECT_LOGIC.md)。

## 2. 项目部署后会运行什么

SKYMIRROR 不是单一脚本，而是一套完整运行链路：

1. 后端守护进程定时拉取新加坡交通摄像头图片。
2. LangGraph 工作流执行图像 guardrail、VLM、validator、orchestrator、expert、alert manager。
3. 运行结果写入本地数据目录。
4. Dashboard 从运行产物中读取状态、告警、日报和最新帧。
5. 后台定时任务每天 `00:05 UTC` 自动生成日报。

部署成功后，通常至少会有两个运行面：

- `daemon`
  负责持续抓图和分析。
- `dashboard`
  负责展示运行状态和历史结果。

## 3. 前置要求

### 3.1 必备软件

- Python `3.11+`
- `uv`（推荐）或 `pip`
- Docker 与 Docker Compose（如需容器部署）

### 3.2 必备外部能力

- OpenAI API Key
- Pinecone 账号与索引

### 3.3 可选外部能力

- LangSmith
  用于 tracing，不开也能运行。
- LTA DataMall API Key
  用于告警侧实时事件补充，不填也可以跑主链路。

## 4. 目录与持久化说明

部署时重点关注以下目录：

- `data/frames/`
  摄像头抓取的帧图。
- `data/oa_log/`
  每次运行的 `RunRecord` JSONL 日志。
- `data/alerts/`
  告警输出。
- `data/reports/`
  日报 Markdown。
- `data/rag/`
  三个 expert 的本地语料目录。
- `data/sources/`
  摄像头参考数据和新加坡官方资料缓存。
- `governance/`
  运行治理策略与发布阈值。

容器部署时，建议至少持久化这些路径：

- `/app/data/oa_log`
- `/app/data/reports`
- `/app/data/alerts`
- `/app/data/frames`
- `/app/data/dashboard`

## 5. 环境变量

项目提供了现成模板 [`.env.example`](../.env.example)。

先复制：

```bash
cp .env.example .env
```

### 5.1 最关键变量

这些变量建议优先填好，否则主链路无法稳定工作：

```dotenv
OPENAI_API_KEY=...
OPENAI_VLM_MODEL=gpt-5.4
OPENAI_GUARDRAIL_MODEL=gpt-5.4-mini
OPENAI_VALIDATOR_MODEL=gpt-5.4
OPENAI_EXPERT_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

PINECONE_API_KEY=...
PINECONE_INDEX_NAME=skymirror-rag
PINECONE_INDEX_HOST=...
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1

PROCESSING_INTERVAL_SECONDS=20
TARGET_CAMERA_ID=4798
FRAMES_DIR=data/frames
OA_LOG_DIR=data/oa_log
LOG_LEVEL=INFO
```

### 5.2 可选但推荐

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=skymirror

LTA_API_KEY=...
KEEP_FRAME_HISTORY=true
RAG_TOP_K=5
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
```

### 5.3 摄像头选择规则

后端守护进程读取摄像头 ID 的优先级如下：

1. `TARGET_CAMERA_IDS`
2. `data/sources/traffic_camera_reference.json` 中前两个摄像头
3. `TARGET_CAMERA_ID`
4. 默认值 `4798`

如果你只想固定跑一个摄像头，最稳妥的做法是直接设置：

```dotenv
TARGET_CAMERA_IDS=4798
TARGET_CAMERA_ID=4798
```

## 6. 本地部署

### 6.1 安装依赖

推荐使用 `uv`：

```bash
uv sync --dev
```

如果你使用 `pip`：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 6.2 准备 RAG 语料

项目内置了三类 namespace：

- `traffic-regulations`
- `safety-incidents`
- `road-conditions`

先拉取并标准化新加坡官方资料，再写入 Pinecone：

```bash
uv run skymirror-rag-bootstrap-sg --ingest --clear-first
```

如果你已经准备好了 `data/rag/` 目录，只想重新写入 Pinecone：

```bash
uv run skymirror-rag-ingest --clear-first
```

说明：

- `--clear-first` 会先清空目标 namespace，再重新写入。
- 第一次写入 Pinecone 时，程序会在索引不存在时自动尝试创建索引。
- 如果 Pinecone 已存在索引但未就绪，程序会等待索引 ready。
- 这一步至少要在首次完整部署前执行一次；`docker compose up` 不会自动帮你做 ingest。

### 6.3 本地单次验证

先跑一轮单次抓图分析：

```bash
uv run python -m skymirror.main --once
```

如果你要用本地图片做冒烟验证：

```bash
uv run python -m skymirror.main --image /absolute/path/to/frame.jpg
```

如果你只想生成日报：

```bash
uv run python -m skymirror.main --report
```

### 6.4 启动本地 daemon

```bash
uv run python -m skymirror.main
```

默认行为：

- 持续轮询摄像头
- 每轮处理后写入 `RunRecord`
- 自动维护 dashboard runtime 状态
- 在 `00:05 UTC` 触发日报任务

### 6.5 启动本地 dashboard

```bash
uv run python -m skymirror.dashboard.server --host 0.0.0.0 --port 8787
```

访问地址：

```text
http://127.0.0.1:8787
```

注意：

- 本地 dashboard 默认端口是 `8787`。
- dashboard 进程会尝试自行拉起一个后端 daemon，并支持切换摄像头。
- 如果你已经单独启动了 `skymirror.main`，需要注意不要和 dashboard 管理的后端产生重复运行。

## 7. Docker 部署

### 7.1 构建镜像

项目已经自带 [`Dockerfile`](../Dockerfile)。

手动构建：

```bash
docker build -t skymirror:latest .
```

### 7.2 直接运行单容器

运行 daemon：

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data/oa_log:/app/data/oa_log" \
  -v "$(pwd)/data/reports:/app/data/reports" \
  -v "$(pwd)/data/alerts:/app/data/alerts" \
  -v "$(pwd)/data/frames:/app/data/frames" \
  skymirror:latest
```

运行 dashboard：

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data/oa_log:/app/data/oa_log:ro" \
  -v "$(pwd)/data/reports:/app/data/reports:ro" \
  -v "$(pwd)/data/alerts:/app/data/alerts:ro" \
  -v "$(pwd)/data/dashboard:/app/data/dashboard" \
  skymirror:latest \
  python -m skymirror.dashboard.server --host 0.0.0.0 --port 8000
```

## 8. Docker Compose 部署

项目已经自带 [`docker-compose.yml`](../docker-compose.yml)，包含两个服务：

- `daemon`
- `dashboard`

前提：

- `.env` 已准备好
- Pinecone 索引已经完成至少一次 RAG ingest

启动：

```bash
docker compose up --build -d
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f daemon
docker compose logs -f dashboard
```

停止：

```bash
docker compose down
```

Dashboard 访问地址：

```text
http://127.0.0.1:8000
```

这里要特别注意一个差异：

- 本地命令行默认 dashboard 端口是 `8787`
- `docker-compose.yml` 里 dashboard 暴露端口是 `8000`

## 9. LangGraph Studio / 图调试

项目根目录有 [`langgraph.json`](../langgraph.json)，图入口是：

- `src/skymirror/graph/graph.py:app`

如果你本地已经安装 `langgraph-cli`，并且 `.env` 已就绪，可以用于开发态调试。由于仓库是 `src/` 布局，建议确保：

```dotenv
PYTHONPATH=src
```

## 10. 运行结果如何验证

部署完成后，可以从四个层面检查。

### 10.1 后端日志

确认 daemon 启动后会打印配置与循环状态，且没有持续报错。

### 10.2 数据产物

确认以下目录出现新文件：

- `data/frames/`
- `data/oa_log/`
- `data/alerts/`
- `data/reports/`

其中最关键的是 `data/oa_log/`，因为它是 dashboard 和日报的事实源。

### 10.3 Dashboard 健康检查

本地 dashboard：

```bash
curl http://127.0.0.1:8787/health
```

Docker Compose dashboard：

```bash
curl http://127.0.0.1:8000/health
```

如果成功，应返回：

```json
{"status":"ok"}
```

### 10.4 离线治理校验

可以运行项目自带的离线评估脚本：

```bash
uv run python -m scripts.evaluate_runtime
```

它会基于 `tests/fixtures/` 验证：

- RunRecord schema 合法率
- guardrail 回归率
- validator 回归率
- expert routing 回归率
- alert evidence 完整率
- report generation 成功率

## 11. 推荐部署顺序

如果你是第一次把项目完整拉起来，建议按这个顺序执行：

1. 复制 `.env.example` 为 `.env` 并填好 OpenAI / Pinecone。
2. 安装依赖。
3. 运行 `uv run skymirror-rag-bootstrap-sg --ingest --clear-first` 初始化语料。
4. 执行 `uv run python -m skymirror.main --once` 做一次后端冒烟。
5. 确认 `data/oa_log/` 和 `data/frames/` 有产物。
6. 启动 dashboard 检查页面。
7. 再切到常驻 daemon 或 `docker compose up -d`。

## 12. 生产部署建议

### 12.1 环境建议

- 使用专用 `.env` 或 Secret 管理系统，不要把真实密钥写入镜像。
- 为 `data/oa_log`、`data/reports`、`data/alerts`、`data/frames` 做持久化挂载。
- 把日志采集接到统一日志平台。
- 给 dashboard 前面加反向代理和访问控制。

### 12.2 资源建议

- daemon 和 dashboard 分开部署更清晰。
- 如果计划多摄像头并行运行，重点关注 OpenAI 请求速率和 Pinecone 吞吐。
- `PROCESSING_INTERVAL_SECONDS` 不建议一开始设得太短，先从 `20` 秒验证稳定性。

### 12.3 运维建议

- 定期检查 `data/frames/`、`data/oa_log/` 磁盘占用。
- 为 `docker compose logs` 或进程日志配置轮转。
- 保留 LangSmith tracing 作为问题定位手段。

## 13. 常见问题

### 13.1 为什么 dashboard 能打开，但没有数据

常见原因：

- daemon 没有成功启动
- `.env` 中 OpenAI / Pinecone 没配全
- `data/oa_log/` 没有产生记录
- dashboard 读取的持久化目录和 daemon 写入的目录不是同一份

### 13.2 为什么专家阶段报 Pinecone 相关错误

因为 expert 的 RAG 检索依赖 Pinecone。请检查：

- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `PINECONE_INDEX_HOST`
- 目标 namespace 是否已经 ingest

### 13.3 为什么本地端口和容器端口不一样

这是代码和编排配置的设计差异：

- `skymirror.dashboard.server` 默认端口是 `8787`
- `docker-compose.yml` 显式改成了 `8000`

两者都正确，只是运行方式不同。

### 13.4 为什么只启动 dashboard 也会拉起后端

本地 dashboard 内置了 `DashboardRuntimeManager`，会自动尝试启动一个后端 daemon，方便单机演示和开发调试。这和 Compose 模式下前后端分服务运行不冲突。

## 14. 建议作为交付基线的命令

### 本地最短路径

```bash
cp .env.example .env
uv sync --dev
uv run skymirror-rag-bootstrap-sg --ingest --clear-first
uv run python -m skymirror.main --once
uv run python -m skymirror.dashboard.server --host 0.0.0.0 --port 8787
```

### Compose 最短路径

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
```
