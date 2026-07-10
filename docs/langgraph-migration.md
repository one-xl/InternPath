# LangGraph Migration

LangGraph is now the orchestration layer for InternPath Agent workflows where graph execution has real value.

## Migrated Paths

- Resume Agent worker jobs use `LangGraphAgenticOrchestrator` by default.
- Explicit `pipeline` compatibility runs use the same LangGraph state machine with `json_action` tool calling.
- Background resume analysis with Agent rewriting uses `LangGraphAgenticOrchestrator`.
- AI Service workflow execution uses LangGraph through `WorkflowEngine`.

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
