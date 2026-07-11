from __future__ import annotations


MIGRATION_VERSION = "20260710_resume_advisor_v1"
SOFT_DELETE_MIGRATION_VERSION = "20260710_resume_advisor_v2_soft_delete"


def run_resume_advisor_migrations(cursor) -> None:
    """Apply the additive, idempotent schema required by ResumeAdvisor."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cursor.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,))
    base_migration_applied = cursor.fetchone() is not None

    statements = [
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);",
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS parent_resume_id VARCHAR(255);",
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE;",
        "ALTER TABLE resumes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;",
        "UPDATE resumes SET content_hash = encode(digest(parsed_json::text, 'sha256'), 'hex') WHERE content_hash IS NULL OR content_hash = '';",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resumes_user_content_hash ON resumes(user_id, content_hash);",
        "CREATE INDEX IF NOT EXISTS idx_resumes_user_name_version ON resumes(user_id, file_name, version_no DESC);",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS interaction_mode VARCHAR(50) NOT NULL DEFAULT 'artifact_legacy';",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS analysis_record_id VARCHAR(255);",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS resume_content_hash VARCHAR(64);",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS jd_content_hash VARCHAR(64);",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS title VARCHAR(255) NOT NULL DEFAULT '';",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS session_status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED';",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS active_run_id VARCHAR(255);",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP;",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS user_satisfied_at TIMESTAMP;",
        "ALTER TABLE agent_resume_tasks ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP;",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS sequence_no INTEGER;",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS message_kind VARCHAR(50) NOT NULL DEFAULT 'text';",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb;",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(255);",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS run_id VARCHAR(255);",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS parent_turn_id UUID;",
        "ALTER TABLE agent_resume_turns ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED';",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_resume_turns_client_message ON agent_resume_turns(user_id, task_id, client_message_id) WHERE client_message_id IS NOT NULL;",
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_turns_sequence ON agent_resume_turns(user_id, task_id, sequence_no);",
        """
        CREATE TABLE IF NOT EXISTS agent_resume_runs (
            id VARCHAR(255) PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE,
            user_id VARCHAR(255) NOT NULL,
            trigger_message_id UUID,
            status VARCHAR(50) NOT NULL,
            rq_job_id VARCHAR(255),
            trace_id VARCHAR(255) NOT NULL,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            error_code VARCHAR(100),
            error_message TEXT,
            telemetry_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_runs_session ON agent_resume_runs(user_id, session_id, created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_runs_slo ON agent_resume_runs(user_id, created_at DESC);",
        """
        CREATE TABLE IF NOT EXISTS agent_resume_suggestions (
            id VARCHAR(255) PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE,
            user_id VARCHAR(255) NOT NULL,
            version INTEGER NOT NULL,
            parent_suggestion_id VARCHAR(255),
            target_block_id VARCHAR(255) NOT NULL,
            original_text_hash VARCHAR(64) NOT NULL,
            location_json JSONB NOT NULL,
            original_text TEXT NOT NULL,
            proposed_text TEXT NOT NULL,
            copy_text TEXT NOT NULL,
            issue TEXT NOT NULL,
            rationale TEXT NOT NULL,
            expected_impact TEXT NOT NULL,
            priority VARCHAR(20) NOT NULL,
            jd_requirement_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            resume_evidence_block_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            user_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            fact_status VARCHAR(30) NOT NULL,
            fact_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(30) NOT NULL DEFAULT 'proposed',
            created_run_id VARCHAR(255),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, target_block_id, version)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_suggestions_session ON agent_resume_suggestions(user_id, session_id, created_at DESC);",
        """
        CREATE TABLE IF NOT EXISTS agent_resume_facts (
            id VARCHAR(255) PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE,
            user_id VARCHAR(255) NOT NULL,
            claim_key VARCHAR(255) NOT NULL,
            claim_value TEXT NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            status VARCHAR(30) NOT NULL,
            scope VARCHAR(30) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, claim_key, claim_value)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_facts_session ON agent_resume_facts(user_id, session_id, status);",
        """
        CREATE TABLE IF NOT EXISTS agent_resume_events (
            id VARCHAR(255) PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL REFERENCES agent_resume_tasks(task_id) ON DELETE CASCADE,
            user_id VARCHAR(255) NOT NULL,
            sequence_no INTEGER NOT NULL,
            run_id VARCHAR(255),
            event_type VARCHAR(50) NOT NULL,
            message_id UUID,
            suggestion_id VARCHAR(255),
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, sequence_no)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_resume_events_resume ON agent_resume_events(user_id, session_id, sequence_no);",
    ]
    if not base_migration_applied:
        for statement in statements:
            cursor.execute(statement)
        cursor.execute("INSERT INTO schema_migrations (version) VALUES (?) RETURNING version", (MIGRATION_VERSION,))

    cursor.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (SOFT_DELETE_MIGRATION_VERSION,))
    if cursor.fetchone() is None:
        cursor.execute("ALTER TABLE resumes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;")
        cursor.execute(
            "INSERT INTO schema_migrations (version) VALUES (?) RETURNING version",
            (SOFT_DELETE_MIGRATION_VERSION,),
        )
