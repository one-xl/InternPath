# InternPath

InternPath 是面向个人求职决策的工作台，用于分析岗位 JD、评估匹配度、沉淀历史分析，并通过 Agent 工作流优化简历。

## 技术栈

- Frontend: React + Vite + TypeScript
- Backend: FastAPI + Pydantic v2
- AI Service: FastAPI microservice, structured RAG, verification workflow
- Data: PostgreSQL + pgvector
- Background jobs: Redis + RQ
- Extension: Chrome Manifest V3

## 必需基础设施

InternPath 运行时只支持 PostgreSQL + pgvector，不提供 SQLite 运行模式。长任务统一进入 Redis/RQ 队列。

必需环境变量：

```env
DATABASE_URL=postgresql://app_user:app_password@localhost:5432/job_dashboard
REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=internpath-default
RQ_JOB_TIMEOUT_SECONDS=1800
RQ_RESULT_TTL_SECONDS=86400
SESSION_SECRET=your_random_secret_here
MODEL_SECRET_ENCRYPTION_KEY=your_encryption_key_here
GEMINI_API_KEY=your_gemini_api_key
LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-1-5-pro-32k-250115
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
```

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

cd frontend
npm install
cd ..

Copy-Item .env.example .env
docker compose up -d
.\start_internpath.cmd
```

默认地址：

- React workbench: `http://127.0.0.1:5173`
- FastAPI backend: `http://127.0.0.1:8787`
- AI service: `http://127.0.0.1:8000`

默认开发账号：

- Email: `admin@example.com`
- Password: `ChangeMe123!`

## 手动启动

```powershell
# Terminal 1: AI Service
cd ai-service
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: RQ Worker
.\.venv\Scripts\python.exe -m backend.rq_worker

# Terminal 3: Backend
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8787

# Terminal 4: Frontend
cd frontend
npm run dev -- --port 5173
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q

cd ai-service
..\.venv\Scripts\python.exe -m pytest tests -q

cd ..\frontend
npm run build
```

后端测试需要可用的 `DATABASE_URL` 与 `REDIS_URL`。本地 CI 如需跑集成测试，应准备 PostgreSQL/pgvector 与 Redis。

## 部署

Linux/Debian 部署脚本会安装 PostgreSQL/pgvector、Redis、Python 依赖，构建前端，并创建三个 systemd 服务：

- `internpath`: Backend API
- `internpath-ai`: AI Service
- `internpath-worker`: RQ Worker

```bash
cd /opt/internpath
chmod +x deploy/server_install.sh
APP_DIR=/opt/internpath APP_PORT=8502 SERVICE_NAME=internpath REQUIREMENTS_FILE=/opt/internpath/requirements.server.txt ./deploy/server_install.sh
```

## 故障排查

| 问题 | 检查项 |
| --- | --- |
| 数据库连接失败 | PostgreSQL 是否运行、`DATABASE_URL` 是否为 PostgreSQL URL、`vector` 扩展是否可创建 |
| 后台任务不执行 | Redis 是否运行、`REDIS_URL` 是否可达、`backend.rq_worker` 是否在运行 |
| AI 分析失败 | `AI_SERVICE_BASE_URL` 是否正确、AI service 是否健康 |
| 前端构建失败 | `cd frontend && npm install && npm run build` |

## 迁移说明

`deploy/migrate_to_postgres.py` 仅用于把历史 SQLite 数据迁移到 PostgreSQL。迁移工具不代表运行时支持 SQLite。
