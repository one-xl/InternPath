# InternPath Agent 企业级优化计划

## 目标

将 InternPath 的 Agent 与 RAG 能力从本地轻量实现升级为企业级运行形态：

- PostgreSQL + pgvector 作为唯一运行时数据源
- Redis + RQ 承载长任务调度
- 后端统一通过确定性的 `Orchestrator` 运行简历 Agent
- AI Service 保持节点化工作流，并输出一致的证据、日志与质量评估

## 不可协商决策

- 数据库只支持 PostgreSQL。`DATABASE_URL` 缺失、非 PostgreSQL URL 或连接失败时直接启动失败。
- 向量能力以 pgvector 为标准能力。`vector` 扩展无法启用时直接失败。
- 长任务只通过 Redis/RQ 入队运行。`REDIS_URL` 缺失或 Redis 不可用时直接失败。
- 简历优化只使用新版 `backend.agents.orchestrator.Orchestrator`。
- AI Service 的 workflow log 由 `WorkflowEngine` 统一生成，节点不再追加重复日志。
- 环境配置由部署环境解决，不提供 SQLite 或本地后台任务兜底。

## 目标架构

```text
React/Vite frontend
        |
        v
FastAPI backend
        |
        +--> PostgreSQL + pgvector
        |
        +--> Redis/RQ queue
        |        |
        |        v
        |   RQ worker -> Orchestrator / background analysis
        |
        +--> AI Service FastAPI
                 |
                 +--> Structured RAG
                 +--> Evidence verification
                 +--> Quality gate
```

## 落地清单

- [x] PostgreSQL-only 数据库运行时
- [x] 数据库 wrapper 与 `Database.is_postgres` 加运行时 invariant，拒绝非 PostgreSQL 模式
- [x] 强制 `DATABASE_URL`，拒绝非 PostgreSQL URL
- [x] 强制启用 `pgcrypto` 与 `vector` 扩展
- [x] `knowledge_chunk.embedding` 使用 pgvector 存储
- [x] 知识 chunk 上传时生成并保存 embedding
- [x] AI Service 文档 schema 接收结构化 section 元数据和 embedding
- [x] 新增 Redis/RQ 队列适配器和 worker 入口
- [x] async analysis、background resume analysis、resume Agent workflow 统一入队
- [x] `/api/analyze` 移除同步执行路径，统一创建 `analysis_task` 并通过 Redis/RQ 入队
- [x] 后台简历分析切换到新版 `Orchestrator.run_orchestration`
- [x] 旧版 `execute_resume_agent_workflow` 禁止作为运行入口，避免绕开 Orchestrator
- [x] Agent 偏好记忆使用 PostgreSQL `agent_preferences`，不再保留 MongoDB/local stub
- [x] AI Service workflow 日志由 engine 统一生成
- [x] 大模型决策、AgentPlanner 计划生成与 AI Service 增强校验失败时直接失败，不再返回本地启发式分析兜底
- [x] `.env.example`、README、AGENTS 和部署文档改为 PostgreSQL/Redis 硬依赖
- [x] Docker Compose 增加 Redis
- [x] Windows/Linux/systemd 启动链路增加 RQ worker
- [x] 根据实际 PostgreSQL/Redis 环境补跑后端集成测试
- [x] 根据生产模型配置补跑完整 Agent E2E 测试

## 验收标准

- PostgreSQL 不可用时没有运行时路径会静默切到 SQLite。
- 新的 Agent/background task 不再使用 FastAPI in-process background execution。
- Agent resume optimization 和 background analysis 使用同一套 Orchestrator。
- 知识库 chunk 的 embedding 能从 PostgreSQL 传递到 AI Service retrieval。
- AI Service workflow logs 不再由节点重复追加。
- 配置、依赖、启动脚本和部署文档都声明 PostgreSQL/pgvector 与 Redis/RQ 为必需基础设施。

## 验证记录

验证日期：2026-07-05

- 后端全量测试：`.\.venv\Scripts\python.exe -m pytest -q`，结果 `83 passed, 1 skipped`
- AI Service 测试：`cd ai-service; ..\.venv\Scripts\python.exe -m pytest tests -q`，结果 `22 passed`
- 前端构建：`cd frontend; npm run build`，结果通过；Vite 仅提示 bundle chunk 超过 500 kB
- Live Agent E2E：`INTERNPATH_RUN_LIVE_E2E=1` 后运行 `tests/test_agent_resume_e2e.py::test_agent_resume_e2e`，结果 `1 passed`
- 服务健康检查：Backend `/api/health` 返回 `ok=true, database=connected`；AI Service `/health` 返回 `status=ok`
- RQ 队列检查：`internpath-default` 队列 `jobs=0, started=0, failed=0`
- 浏览器显示检查：工作台、Agent 简历优化页、管理员控制台中文显示正常，未检测到乱码，控制台无 error

## 追加收口验证

- PostgreSQL-only 运行时约束测试：`tests/test_postgres_isolation.py::test_database_runtime_rejects_non_postgres_paths`，并确认测试 schema 不再创建 `.db` 标记文件
- 模型/AI Service 不可用失败语义测试：`tests/test_analysis_persistence.py::test_service_build_personal_decision_fails_without_model`、`tests/test_analysis_persistence.py::test_service_analyze_jd_with_guardrails_fails_when_ai_service_unavailable`
- AgentPlanner 计划生成失败语义测试：`tests/test_agent_phase2.py::test_agent_planner_fails_when_model_call_fails`、`tests/test_agent_phase2.py::test_agent_planner_fails_on_invalid_json_plan`、`tests/test_agent_phase2.py::test_agent_planner_accepts_model_empty_steps`
