# Agent Resume Framework

## Entry Points

- API start: `POST /api/agent/resume/optimize`
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
