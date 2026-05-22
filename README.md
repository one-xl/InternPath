# InternPath

InternPath 是一个面向个人自用的求职决策工作台。它把目标岗位 JD、个人简历、项目材料和历史分析放在同一条工作流里，帮助你判断一份岗位是否值得投、简历应该怎么改、短期需要补哪些证据和技能。

## Frontend

项目已经彻底切换为 `React + Vite + TypeScript` 前端，不再保留旧版 Python 页面入口。

## 核心能力

- 投递决策：输出"建议投 / 谨慎投 / 不建议投"、匹配度、关键理由和致命缺口。
- 简历改造：给出可直接复制的简历表达，并标记还需要补证据的经历。
- 个人材料：上传简历、项目说明、实习经历或学习资料，作为 JD 分析依据。
- 历史沉淀：分析结果自动保存到 PostgreSQL（或本地 SQLite），支持多用户隔离。
- 专家调试：RAG、证据校验、幻觉风险和工作流日志保留在折叠区。

## 技术栈

- Frontend：React、Vite、TypeScript
- Backend：FastAPI
- AI/业务：Python、Pydantic、OpenAI-compatible SDK
- Data：PostgreSQL（推荐）/ SQLite（本地开发回退）
- Optional：独立 `ai-service` 增强校验服务

## 快速开始

### 方式一：PostgreSQL（推荐）

1. 启动 PostgreSQL。

```powershell
docker compose up -d
```

2. 安装 Python 依赖。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. 安装前端依赖。

```powershell
cd frontend
npm install
cd ..
```

4. 创建 `.env` 并填写配置。

```powershell
Copy-Item .env.example .env
```

示例：

```env
DATABASE_URL=postgresql://app_user:app_password@localhost:5432/job_dashboard
SESSION_SECRET=your_random_secret_here
MODEL_SECRET_ENCRYPTION_KEY=your_encryption_key_here
GEMINI_API_KEY=your_gemini_api_key
LLM_API_KEY=your_doubao_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-1-5-pro-32k-250115
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
```

5. 启动个人工作台。

```powershell
.\start_internpath.cmd
```

首次启动时会自动建表并创建默认开发账号：

- 邮箱：`admin@example.com`
- 密码：`ChangeMe123!`

### 方式二：SQLite（本地开发回退）

不设置 `DATABASE_URL` 即可自动使用本地 SQLite。步骤同上，跳过第 1 步即可。

默认地址：

- React 前端：`http://127.0.0.1:5173`
- FastAPI 后端：`http://127.0.0.1:8787`
- ai-service：`http://127.0.0.1:8000`

## 手动启动

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
```

前端：

```powershell
cd frontend
npm run dev -- --port 5173
```

## 测试

根项目测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端构建：

```powershell
cd frontend
npm run build
```

ai-service 测试：

```powershell
cd ai-service
..\.venv\Scripts\python.exe -m pytest tests -q
```

## 生产部署注意事项

1. **不要提交 `.env` 文件**：`.gitignore` 已配置忽略。
2. **不要公开暴露 PostgreSQL**：生产环境数据库仅限内网访问。
3. **使用 HTTPS**：生产环境务必启用 TLS。设置 `NODE_ENV=production` 后，Cookie 自动启用 `secure` 标志。
4. **设置 `FRONTEND_ORIGIN`**：生产环境必须配置前端域名，CORS 仅允许该来源。
5. **修改默认密码**：开发默认账号 `admin@example.com` / `ChangeMe123!` 必须在生产环境中修改。
6. **轮换泄露的 API Key**：如果 API Key 泄露，立即轮换。
7. **VITE_* 变量不含密钥**：前端环境变量仅限公开配置。
8. **会话持久化**：会话存储在数据库中（`sessions` 表），服务器重启不会丢失已登录会话。过期会话在启动时自动清理。
9. **Cookie 安全**：`httpOnly`、`SameSite=Lax` 始终启用。生产环境 (`NODE_ENV=production`) 额外启用 `secure`。
10. **CSRF 防护**：当前依赖 `SameSite=Lax` Cookie 策略防护 CSRF。所有状态变更接口使用 POST/PUT/DELETE 方法，浏览器不会跨站自动携带 Cookie。如需更强防护，可后续添加 CSRF Token。
11. **CORS 策略**：开发环境允许 localhost 来源；生产环境仅允许 `FRONTEND_ORIGIN` 配置的域名，不允许通配符。

## 数据隔离

所有用户数据（分析记录、草稿、设置、模型配置）均通过 `user_id` 字段隔离。后端从认证会话中获取当前用户 ID，前端不控制数据归属。

## 环境变量说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `DATABASE_URL` | 生产必填 | PostgreSQL 连接字符串，留空使用 SQLite |
| `SESSION_SECRET` | 否 | 会话密钥 |
| `MODEL_SECRET_ENCRYPTION_KEY` | 否 | API Key 加密密钥 |
| `GEMINI_API_KEY` | 是 | Gemini API Key（后端专用） |
| `LLM_API_KEY` | 是 | Doubao/DeepSeek API Key（后端专用） |
| `LLM_BASE_URL` | 否 | LLM API 地址 |
| `LLM_MODEL` | 否 | 默认 LLM 模型 |
| `AI_SERVICE_BASE_URL` | 否 | AI 服务地址 |
| `NODE_ENV` | 生产必填 | `development` 或 `production` |
| `FRONTEND_ORIGIN` | 生产必填 | 前端部署域名，如 `https://internpath.example.com` |

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 数据库连接失败 | 检查 PostgreSQL 是否启动，`DATABASE_URL` 是否正确 |
| 登录失败 | 检查密码是否正确，确认后端已启动 |
| 历史记录不保存 | 检查数据库连接，查看后端日志 |
| 前端构建失败 | 运行 `cd frontend && npm install && npm run build` |

## 隐私

InternPath 默认面向个人本地使用。`.env`、数据库文件、日志、用户数据和上传材料不会进入版本库。上传的简历和项目材料保存在数据库中，请按自己的隐私要求管理工作目录和备份。
