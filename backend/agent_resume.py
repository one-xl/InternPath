from __future__ import annotations

from typing import Any, Optional

from backend.agents.tools.workspace_tools import (
    get_safe_workspace_path,
    get_workspace_dir,
    tool_list_files,
    tool_read_file,
    tool_write_file,
)
from backend.agents.tools.resume_section_tools import (
    tool_analyze_gap,
    tool_extract_resume_sections,
    tool_generate_modification_diff,
    tool_replace_resume_section,
    tool_rewrite_section,
    tool_rewrite_section_retry,
)
from backend.agents.tools.docx_tools import (
    convert_docx_to_pdf,
    extract_docx_style_profile,
    generate_docx_from_markdown,
    update_docx_resume_from_log,
)
from backend.agents.tools.hallucination_tools import (
    check_resume_fact_integrity,
    tool_verify_anti_hallucination,
)


async def execute_resume_agent_workflow(
    user_id: Any,
    task_id: str,
    resume_text: str,
    jd_text: str,
    resume_id: Optional[str] = None,
    original_resume_name: Optional[str] = None,
    config_id: Optional[str] = None,
) -> None:
    raise RuntimeError(
        "Legacy resume Agent workflow is disabled. "
        "Use backend.jobs.run_agent_resume_orchestration_job with Orchestrator.run_orchestration."
    )


__all__ = [
    "check_resume_fact_integrity",
    "convert_docx_to_pdf",
    "execute_resume_agent_workflow",
    "extract_docx_style_profile",
    "generate_docx_from_markdown",
    "get_safe_workspace_path",
    "get_workspace_dir",
    "tool_analyze_gap",
    "tool_extract_resume_sections",
    "tool_generate_modification_diff",
    "tool_list_files",
    "tool_read_file",
    "tool_replace_resume_section",
    "tool_rewrite_section",
    "tool_rewrite_section_retry",
    "tool_verify_anti_hallucination",
    "tool_write_file",
    "update_docx_resume_from_log",
]
