# AGENTS.md

## Project Overview

InternPath is a personal job decision workbench that helps users analyze job postings, evaluate fit, and improve resumes. It combines a React frontend, FastAPI backend, Redis/RQ worker, PostgreSQL/pgvector data layer, and a separate AI microservice for RAG and hallucination control.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React Frontend │───▶│  FastAPI Backend │───▶│   AI Service    │
│   (Vite, TS)     │    │  (Port 8787)     │    │   (Port 8000)   │
│   Port 5173      │    │                  │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                      │
         │                      ▼
         │              ┌─────────────────┐
         │              │   PostgreSQL    │
         │              │   + pgvector    │
         └──────────────┴─────────────────┘
```

**Key Directories:**
- `backend/` - FastAPI backend with all API endpoints
- `frontend/` - React + Vite + TypeScript frontend
- `ai-service/` - Separate FastAPI service for RAG, verification, and workflow execution
- `deploy/` - Deployment scripts (PowerShell, shell, systemd)
- `tests/` - Backend test suite
- `chrome-extension/` - Chrome 浏览器插件（Manifest V3），一键抓取 BOSS直聘/牛客网 职位并导入工作台

## Quick Start Commands

### Setup

```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend
npm install
cd ..

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Start All Services

```powershell
# One-command start (Windows)
.\start_internpath.cmd

# Or manually:
# Terminal 1: Backend
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8787

# Terminal 2: AI Service
cd ai-service
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 3: RQ Worker
.\.venv\Scripts\python.exe -m backend.rq_worker

# Terminal 4: Frontend
cd frontend
npm run dev -- --port 5173
```

### Stop Services

```powershell
.\stop_internpath.cmd
```

### Restart Services

```powershell
.\restart_internpath.cmd
```

## Testing

### Backend Tests

```powershell
# Run all backend tests
.\.venv\Scripts\python.exe -m pytest -q

# Run specific test file
.\.venv\Scripts\python.exe -m pytest tests/test_fastapi_backend.py -q

# Run with verbose output
.\.venv\Scripts\python.exe -m pytest -v
```

### AI Service Tests

```powershell
cd ai-service
..\.venv\Scripts\python.exe -m pytest tests -q
```

### Frontend Build Check

```powershell
cd frontend
npm run build
```

## Environment Variables

**Required:**
- `DATABASE_URL` - PostgreSQL connection string. Runtime supports PostgreSQL + pgvector only.
- `REDIS_URL` - Redis connection string for RQ background jobs.
- `GEMINI_API_KEY` - Gemini API key (backend only)
- `LLM_API_KEY` - Doubao/DeepSeek API key (backend only)

**Optional:**
- `RQ_QUEUE_NAME` - RQ queue name (default: `internpath-default`)
- `RQ_JOB_TIMEOUT_SECONDS` - RQ job timeout in seconds (default: `1800`)
- `RQ_RESULT_TTL_SECONDS` - RQ result and failure TTL in seconds (default: `86400`)
- `SESSION_SECRET` - Session encryption key
- `MODEL_SECRET_ENCRYPTION_KEY` - API key encryption key
- `LLM_BASE_URL` - LLM API endpoint (default: `https://api.deepseek.com`)
- `LLM_MODEL` - Default LLM model (default: `deepseek-chat`)
- `AI_SERVICE_BASE_URL` - AI service URL (default: `http://127.0.0.1:8000`)

**Production Only:**
- `NODE_ENV=production`
- `FRONTEND_ORIGIN` - Frontend domain for CORS

## Default Credentials

**Development Admin:**
- Configure `INTERNPATH_ADMIN_USERNAME` and `INTERNPATH_ADMIN_PASSWORD` locally.`r`n- Never commit administrator credentials to the repository.

**Database (PostgreSQL):**
- User: `app_user`
- Password: `app_password`
- Database: `job_dashboard`
- Port: `5432`

## Code Conventions

### Python

- **Style**: PEP 8 with 4-space indentation
- **Type Hints**: Use Python 3.10+ type hints (`list[str]`, `dict[str, Any]`)
- **Pydantic**: Use Pydantic v2 for request/response models
- **Async**: Use `async/await` for I/O-bound operations; wrap blocking calls with `asyncio.to_thread()`
- **Database**: PostgreSQL + pgvector only; do not add SQLite runtime fallback paths
- **Error Handling**: Raise `HTTPException` with appropriate status codes and Chinese error messages

### TypeScript/React

- **Style**: ESLint with TypeScript strict mode
- **Components**: Functional components with hooks
- **State Management**: React hooks (`useState`, `useEffect`, `useRef`)
- **Styling**: CSS modules or inline styles
- **API Calls**: Use `fetch` with proper error handling

### File Naming

- **Python**: `snake_case.py`
- **TypeScript**: `PascalCase.tsx` for components, `camelCase.ts` for utilities
- **Tests**: `test_*.py` for Python, `*.test.ts` for TypeScript

## Common Patterns

### Database Queries

```python
# Use parameterized queries
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# Existing helpers use DatabaseCursorWrapper to translate legacy placeholders to PostgreSQL
cursor = DatabaseCursorWrapper(conn.cursor(), is_postgres=db.is_postgres)
cursor.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
user_id = cursor.lastrowid
```

### API Endpoints

```python
@app.post("/api/endpoint")
async def endpoint(
    payload: RequestModel,
    user_id: Any = Depends(current_user_id)
) -> dict[str, Any]:
    # Validate input
    if not payload.field:
        raise HTTPException(status_code=400, detail="错误信息")
    
    # Process request
    result = await asyncio.to_thread(some_blocking_operation, payload.field)
    
    # Return response
    return {"ok": True, "data": result}
```

### Frontend API Calls

```typescript
const response = await fetch("/api/endpoint", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  credentials: "include",
  body: JSON.stringify(data),
});

if (!response.ok) {
  const error = await response.json();
  throw new Error(error.detail || "Request failed");
}

const result = await response.json();
```

## Architecture Decisions

### PostgreSQL + pgvector Only

The application uses PostgreSQL as the only runtime database:
- `DATABASE_URL` is required and must be a PostgreSQL URL
- `pgvector` is required for embedding storage and retrieval
- SQLite may appear only in one-off migration tooling for historical data import

### Redis/RQ Background Jobs

Long-running analysis and Agent workflows must run through Redis/RQ:
- `REDIS_URL` is required
- API endpoints enqueue work and return task IDs
- `backend.rq_worker` consumes the configured `RQ_QUEUE_NAME`

### Session Management

- Sessions stored in database (not memory)
- Cookie-based authentication (`session_id` cookie)
- Session lifetime: 2 hours (7200 seconds)
- Automatic cleanup of expired sessions on startup

### AI Service Separation

The AI service runs as a separate FastAPI application:
- **Port**: 8000 (configurable via `INTERNPATH_AI_PORT`)
- **Purpose**: RAG search, verification, workflow execution
- **Communication**: HTTP API calls from backend
- **Benefits**: Independent scaling, isolation of AI workloads

### File Upload Handling

- Resume files parsed and stored in database (not filesystem)
- Supported formats: PDF, DOCX, TXT
- Maximum file size: 10MB
- Automatic deduplication by filename

## Chrome Extension

`chrome-extension/` 目录包含一个 Manifest V3 浏览器插件，支持从 BOSS直聘和牛客网一键抓取职位信息并导入工作台。

### 核心功能

- **智能填表网申**：扫描页面表单字段，调用 `/api/analysis/tailor-form-fields` 生成 AI 定制文案并自动填入
- **自动回填职位**：抓取当前页面 JD，回填到已打开的 InternPath 工作台分析表单
- **一键后台分析**：直接调用 `/api/jobs/import` 将职位数据发送到后端进行分析

### 技术要点

- 使用 `chrome.storage.local` 存储 API 地址和登录 token
- 支持 Bearer token 和 Cookie 两种认证方式
- Content script 每 1.5 秒自动检测页面变化，触发静默回填
- 通过 `setReactValue()` 兼容 React/Vue 框架的表单输入

### 安装方式

```powershell
# Chrome 浏览器地址栏输入：
chrome://extensions/
# 开启"开发者模式" -> "加载已解压的扩展程序" -> 选择 chrome-extension 目录
```

## Debugging Tips

### Backend Issues

```powershell
# Check backend logs
Get-Content -Path logs\backend.log -Tail 50

# Test database connection
.\.venv\Scripts\python.exe -c "from database import Database; db = Database(); print('DB OK')"

# Reset admin password
.\.venv\Scripts\python.exe reset_admin.py
```

### Frontend Issues

```powershell
# Clear node_modules and reinstall
cd frontend
Remove-Item -Recurse -Force node_modules
npm install

# Check TypeScript errors
npm run build
```

### AI Service Issues

```powershell
# Check AI service logs
Get-Content -Path logs\ai-service.log -Tail 50

# Test AI service health
curl http://127.0.0.1:8000/health
```

## Common Pitfalls

1. **Database Locks**: Don't hold database connections open during long operations
2. **CORS Errors**: Ensure frontend runs on port 5173 and backend allows it
3. **API Key Issues**: Check `.env` file has valid keys, not placeholder values
4. **Session Expiry**: Sessions expire after 2 hours; users need to re-login
5. **File Upload Size**: Files over 10MB will be rejected
6. **PostgreSQL Connection**: PostgreSQL + pgvector must be running before starting backend
7. **Port Conflicts**: Check ports 5173, 8787, and 8000 are not in use by other services

## Production Deployment

### Environment Setup

```bash
# Set production environment
export NODE_ENV=production
export FRONTEND_ORIGIN=https://your-domain.com
export DATABASE_URL=postgresql://user:pass@host:5432/dbname
export REDIS_URL=redis://127.0.0.1:6379/0

# Generate secure secrets
openssl rand -hex 16  # For SESSION_SECRET
openssl rand -hex 32  # For MODEL_SECRET_ENCRYPTION_KEY
```

### Security Checklist

- [ ] Change default admin password
- [ ] Use HTTPS in production
- [ ] Set strong `SESSION_SECRET`
- [ ] Set strong `MODEL_SECRET_ENCRYPTION_KEY`
- [ ] Configure `FRONTEND_ORIGIN` for CORS
- [ ] Use PostgreSQL + pgvector
- [ ] Run Redis and the RQ worker
- [ ] Enable database backups
- [ ] Set up log rotation
- [ ] Configure firewall rules

## Contributing

1. Follow existing code style and patterns
2. Add tests for new features
3. Update documentation for API changes
4. Test against PostgreSQL + pgvector and Redis/RQ
5. Ensure frontend builds without errors
6. Run full test suite before submitting changes

## References

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **React Documentation**: https://react.dev/
- **Vite Documentation**: https://vitejs.dev/
- **Pydantic Documentation**: https://docs.pydantic.dev/
- **PostgreSQL Documentation**: https://www.postgresql.org/docs/
