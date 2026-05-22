# InternPath

InternPath 是一个面向个人自用的求职决策工作台。它把目标岗位 JD、个人简历、项目材料和历史分析放在同一条工作流里，帮助你判断一份岗位是否值得投、简历应该怎么改、短期需要补哪些证据和技能。

## Frontend

项目已经彻底切换为 `React + Vite + TypeScript` 前端，不再保留旧版 Python 页面入口。

## 核心能力

- 投递决策：输出“建议投 / 谨慎投 / 不建议投”、匹配度、关键理由和致命缺口。
- 简历改造：给出可直接复制的简历表达，并标记还需要补证据的经历。
- 个人材料：上传简历、项目说明、实习经历或学习资料，作为 JD 分析依据。
- 历史沉淀：分析结果自动保存到本机 SQLite，方便复盘和比较。
- 专家调试：RAG、证据校验、幻觉风险和工作流日志保留在折叠区。

## 技术栈

- Frontend：React、Vite、TypeScript
- Backend：FastAPI
- AI/业务：Python、Pydantic、OpenAI-compatible SDK
- Data：SQLite
- Optional：独立 `ai-service` 增强校验服务

## 快速开始

1. 安装 Python 依赖。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 安装前端依赖。

```powershell
cd frontend
npm install
cd ..
```

3. 创建 `.env` 并填写模型配置。

```powershell
Copy-Item .env.example .env
```

示例：

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
```

4. 启动个人工作台。

```powershell
.\start_internpath.cmd
```

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

## 隐私

InternPath 默认面向个人本地使用。`.env`、SQLite 数据库、日志、用户数据和上传材料不会进入版本库。上传的简历和项目材料保存在本机 SQLite 中，请按自己的隐私要求管理工作目录和备份。
