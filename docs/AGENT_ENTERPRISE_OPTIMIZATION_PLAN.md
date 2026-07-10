# Agent Enterprise Optimization Plan

## Current Runtime Decisions

- PostgreSQL + pgvector remains the only runtime data layer.
- Redis/RQ remains the long-running task queue.
- Resume Agent orchestration uses LangGraph by default through `LangGraphAgenticOrchestrator`.
- Explicit `pipeline` mode is a LangGraph-native `json_action` compatibility path; it does not invoke the legacy deterministic runtime.
- Background resume analysis with Agent rewriting calls `LangGraphAgenticOrchestrator`.
- AI Service workflow execution uses LangGraph through `WorkflowEngine`.

## Deliberately Non-Graph APIs

These paths stay as ordinary FastAPI handlers because LangGraph would not improve them:

- Auth and session management
- Downloads and artifact reads
- Model configuration CRUD
- File metadata and regular CRUD endpoints
- Simple validation and health checks

## Acceptance Criteria

- Agent resume worker jobs cannot bypass LangGraph.
- Background resume analysis Agent rewriting cannot bypass LangGraph.
- AI Service workflow nodes execute through the LangGraph-backed `WorkflowEngine`.
- `agent_resume_tasks` remains the business source of truth.
- LangGraph checkpointing defaults to PostgreSQL; `memory` is limited to isolated tests.
- Human answers resume the persisted graph with `Command(resume=...)`.
- Agent resume runtime paths do not call the historical deterministic `Orchestrator.run_orchestration` implementation.
