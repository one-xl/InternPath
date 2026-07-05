# Agent Resume Framework

## Entry Points

- API start: `POST /api/agent/resume/optimize`
- API detail: `GET /api/agent/resume/tasks/{task_id}`
- API answer: `POST /api/agent/resume/tasks/{task_id}/answer`
- Worker job: `run_agent_resume_orchestration_job`
- Runtime coordinator: `Orchestrator.run_orchestration`

The API creates an `agent_resume_tasks` row, initializes a bootstrap execution plan, and enqueues the RQ job. The worker runs the Orchestrator and updates the same task row as stages progress.

## State Machine

- `PENDING`: task row exists and waits for a worker.
- `RUNNING`: Orchestrator is actively processing the task.
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

The answer API writes a `user` turn and keeps `human_answer` only as a compatibility field. Orchestrator consumes only unconsumed `user` turns whose `step_index` matches the current step, then marks those turns consumed. This prevents answers for one step from leaking into later steps.

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

Orchestrator imports tools through `backend/agents/tools/`:

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
