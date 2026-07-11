# LangGraph Migration

LangGraph is now the orchestration layer for InternPath Agent workflows where graph execution has real value.

## Migrated Paths

- Resume Agent worker jobs use `LangGraphAgenticOrchestrator` by default.
- Explicit `pipeline` compatibility runs use the same LangGraph state machine with `json_action` tool calling.
- Background resume analysis with Agent rewriting uses `LangGraphAgenticOrchestrator`.
- AI Service workflow execution uses LangGraph through `WorkflowEngine`.
- ResumeAdvisor runs use a separate `LangGraphResumeAdvisor` shell around the evidence-first `ResumeAdvisorGraph`; its RQ entry point is `run_resume_advisor_session_job`. It pauses with `interrupt()` after一条问题或一张建议卡，用户后续操作通过 `Command(resume=...)` 恢复同一会话线程，而不是自动生成文件。

## Non-Graph Paths

These API paths stay as ordinary FastAPI handlers because LangGraph would not improve the behavior:

- Authentication and session management
- Downloads and artifact reads
- Model configuration CRUD
- File metadata and regular CRUD endpoints
- Simple synchronous validation and health checks

## State Ownership

`agent_resume_tasks` remains the business source of truth. LangGraph checkpointing is durable by default:

- `LANGGRAPH_CHECKPOINTER=postgres` (default): checkpoints survive RQ job boundaries and worker restarts.
- `LANGGRAPH_CHECKPOINTER=memory`: isolated tests and single-process experiments only.

Human-in-the-loop pauses use LangGraph `interrupt()`. The answer API enqueues a structured resume payload, and the worker continues the existing graph with `Command(resume=...)` instead of starting again from `START`.

ResumeAdvisor keeps business session state in `agent_resume_tasks` with `interaction_mode=resume_advisor`, while `agent_resume_runs` owns an individual queue execution. User-visible messages, suggestions, facts, and resumable events are persisted separately; worker restart therefore never requires reconstructing a conversation from volatile logs.
