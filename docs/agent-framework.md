# Agent Resume Framework

## ResumeAdvisor（新默认交互）

`resume_advisor` 将简历优化定义为可恢复的对话会话，而不是文件生成任务。新会话不会调用文件写入、段落替换或 DOCX/PDF 导出工具；用户复制建议后自行修改原文件。

- 创建会话：`POST /api/agent/resume/sessions`
- 发送普通消息：`POST /api/agent/resume/sessions/{id}/messages`
- 快照：`GET /api/agent/resume/sessions/{id}`
- 原简历 blocks：`GET /api/agent/resume/sessions/{id}/resume-view`
- 事件续传：`GET /api/agent/resume/sessions/{id}/events?afterSequence=`
- 建议操作：`POST /api/agent/resume/suggestions/{id}/actions`
- 显式结束：`POST /api/agent/resume/sessions/{id}/finish`

每条用户消息都会创建一条 `agent_resume_runs` 记录并通过 RQ 执行一次 Advisor graph。会话状态（`ACTIVE`、`WAITING_FOR_USER`、`READY_FOR_CONFIRMATION`、`SATISFIED`、`ARCHIVED`、`FAILED`）与单次 run 状态（`QUEUED`、`RUNNING`、`PAUSED`、`COMPLETED`、`FAILED`）分离。只有 `/finish` 的 `confirmation=satisfied` 才能使会话进入 `SATISFIED`。

建议恢复不会覆盖历史记录。对任意历史建议执行 `restore` 会追加一条指向原建议的 `parent_suggestion_id` 新版本，只有受支持的事实恢复为可复制的 `accepted` 状态。

简历上传以 SHA-256 内容哈希去重：同名不同内容会创建新版本；同内容才复用已有不可变版本。解析结果中的 `blocks` 保存稳定 ID、原文哈希、顺序、上下文和定位置信度。当前 PDF/DOCX 文本提取没有完整布局树时会明确标记为 `approximate`，不会伪造精确位置。

删除简历版本使用软删除：它会从新会话的候选列表中隐藏，但任何已绑定该版本的 Advisor 会话仍可读取其不可变 blocks 和原始文件快照。

Advisor 的原件预览由受鉴权的 `/resume-file` 提供：PDF 会使用原始页面文本坐标补充可验证的页码与 bbox；DOCX 在浏览器中使用惰性加载的 `docx-preview` 渲染，缺少可靠页级坐标时仍明确标记为近似定位。

`AgentToolProfile.RESUME_ADVISOR` 只公开受领域约束的会话、定位、JD、证据、事实、质量、建议版本和状态转换工具：`get_resume_snapshot`、`get_resume_outline`、`locate_resume_blocks`、`get_analysis_context`、`parse_jd_requirements`、`retrieve_resume_evidence`、`list_confirmed_facts`、`list_resume_preferences`、`analyze_gap_queue`、`draft_resume_suggestion`、`verify_suggestion_facts`、`review_suggestion_quality`、`revise_resume_suggestion`、`record_user_fact`、`save_user_preference`、`request_user_input` 和 `evaluate_session_completion`。

所有 Advisor 工具使用 Pydantic 输入校验，并返回统一的 `ok/data/error/meta` 结构；`meta` 包含工具版本、trace ID、耗时、证据引用和幂等键。工具参数与结果预览默认脱敏。读工具可配置有限重试；追加/状态转换工具不自动重试，且写入用户事实或长期偏好必须在运行时提供显式用户确认。

`verify_suggestion_facts` 只接受原简历 block、当前会话已确认事实或显式保存的资料作为证据，JD 永远只表示岗位要求；`review_suggestion_quality` 在事实通过后执行本地质量门。两项门禁任一失败时不会写入可复制建议。若用户已配置模型，图会复用 `JobDecoder`、`ResumeCopywriter` 和 `HRCritic`；模型不可用时会明确降级为本地保守草拟与质量门。`write_workspace_file`、`replace_resume_section`、`finalize_resume_artifacts` 保留在 `artifact_legacy` profile，只服务历史任务。

背景岗位分析中的 `enable_agent_resume` 同样默认拒绝启动旧产物流程；只有迁移/历史兼容调用显式声明 `legacy_artifact_mode=true` 才能使用旧链路。

## Entry Points

- Legacy API start: `POST /api/agent/resume/optimize`（必须显式提交 `legacy_mode=true`，仅用于历史兼容）
- API detail: `GET /api/agent/resume/tasks/{task_id}`
- API answer: `POST /api/agent/resume/tasks/{task_id}/answer`
- Worker job: `run_agent_resume_orchestration_job`
- Background analysis Agent step: `run_background_resume_analysis(..., enable_agent_resume=True)`
- Runtime coordinator: `LangGraphAgenticOrchestrator` by default; `LangGraphPipelineOrchestrator` provides a LangGraph-native `json_action` compatibility mode.

The API creates an `agent_resume_tasks` row, initializes a bootstrap execution plan, and enqueues the RQ job. The worker runs the LangGraph coordinator and updates the same task row as stages progress. Background resume analysis uses the same LangGraph agentic coordinator when `enable_agent_resume` is enabled.

## LangGraph Scope

LangGraph is used only where it improves orchestration clarity and resumability:

- Default resume Agent mode (`agentic`) runs a graph of `load_task`, `prepare_workspace`, `run_agent_loop`, and `finalize_task`.
- Explicit `pipeline` mode runs the same LangGraph state machine with `json_action`; it no longer calls the legacy deterministic `Orchestrator.run_orchestration` runtime.
- Background resume analysis with Agent resume rewriting calls `LangGraphAgenticOrchestrator`, not the legacy deterministic coordinator.
- AI Service workflow execution uses LangGraph inside `WorkflowEngine`, while preserving the existing node interface and workflow logs.
- Auth, download, model config, file metadata, and ordinary CRUD APIs remain plain FastAPI handlers because graph orchestration would add ceremony without improving behavior.

`agent_resume_tasks` remains the business source of truth. `LANGGRAPH_CHECKPOINTER=postgres` is the default so `interrupt()` checkpoints survive RQ job boundaries and worker restarts. `memory` is reserved for isolated tests.

See `docs/langgraph-migration.md` for the current migration boundary and the API paths that intentionally remain non-graph FastAPI handlers.

## State Machine

- `PENDING`: task row exists and waits for a worker.
- `RUNNING`: LangGraph is actively processing the task.
- `WAITING_FOR_HUMAN`: dialog mode paused at a specific step and wrote an assistant turn.
- `COMPLETED`: final Markdown is stored and downloads are available.
- `FAILED`: a fatal model, schema, storage, or generation error stopped the task.

Execution steps use `PENDING`, `RUNNING`, `COMPLETED`, or `SKIPPED`. `SKIPPED` steps are not selected as active answer targets.

## Conversation Protocol

`agent_resume_turns` is the durable conversation log. Each turn records:

- `task_id`, `user_id`, `step_index`
- `role`: `assistant` or `user`
- `content`
- `answer_type`: `evidence`, `preference`, `skip`, or `clarification`
- `remember`
- `evidence_scope`
- `consumed_at`

The answer API writes a step-scoped `user` turn, keeps `human_answer` only as a compatibility field, and sends the current answer as a LangGraph resume payload. The worker calls `Command(resume=...)` on the existing task thread, and the resumed Agent model input includes that verified answer. `step_index` keeps the durable conversation timeline scoped to the question that produced it.

## Schemas

LLM JSON outputs are validated by Pydantic models in `backend/agents/schemas.py`:

- `ExecutionPlanOutput`
- `JobDecodeOutput`
- `HRCriticOutput`
- `LayoutAuditOutput`

Invalid JSON, missing required fields, invalid enums, or out-of-range scores fail explicitly instead of falling back to a successful-looking default.

## Cache

Agent cache keys are built by `build_cache_key`. Keys include:

- namespace and namespace version
- `AGENT_SCHEMA_VERSION`
- `AGENT_TOOL_VERSION`
- prompt file hash where a namespace uses a prompt file
- normalized payload parts

Default storage is `FileAgentCacheStore`, configured by `AGENT_CACHE_STORE`, `AGENT_CACHE_TTL_SECONDS`, and `AGENT_CACHE_LOCK_TIMEOUT_SECONDS`. The file store uses atomic writes and a lock file for cross-process safety.

Main namespaces:

- `resume_plan_v2`
- `job_decode_v2`
- `resume_section_rewrite_v2`
- `resume_hr_critic_v2`
- `resume_hallucination_check_v2`
- `layout_audit_v2`

## Tool Modules

LangGraph coordinators import tools through `backend/agents/tools/`:

- `workspace_tools.py`: workspace path and file IO
- `resume_section_tools.py`: section extraction, replacement, diff generation
- `hallucination_tools.py`: semantic hallucination check and local fact guard
- `docx_tools.py`: DOCX/PDF generation entry points
- `layout_tools.py`: layout dependency check and page rendering

`backend/agent_resume.py` remains a compatibility surface for older imports while the framework moves toward the tool modules.

## Artifacts

本节只适用于 `artifact_legacy` 历史记录。新的 ResumeAdvisor 会话不创建或展示这些产物。

Workspace files live under `user_data/workspaces/user_{user_id}/task_{task_id}/`.

- `original_resume.txt`
- `job_description.txt`
- `resume_sections.json`
- `modification_log.json`
- `assembled_resume.txt`
- `modification_diff.md`
- `optimized_resume.md`
- `optimized_resume.docx`
- `optimized_resume.pdf`
- `style_profile.json`

`get_safe_workspace_path` rejects absolute paths, `..`, empty path fragments, invalid filename characters, and paths outside the task workspace by `os.path.commonpath`.

## Observability

Every task gets a `trace_id`. Logs include:

- `trace_id`
- `stage`
- `agent`
- `cache_namespace`
- `duration_ms`
- `model_id`

The frontend displays cache stats, stage metadata, and the conversation timeline from `conversationTurns`.

## Failure Strategy

Schema failures, missing task/resume data, unsafe paths, and fatal generation errors mark the task `FAILED` and persist logs plus `error_message`. HITL pauses are normal control flow and surface as `WAITING_FOR_HUMAN`.
