from backend.resume_advisor.tool_runtime import ResumeAdvisorToolRuntime


def test_advisor_tool_runtime_executes_a_profile_scoped_operation_with_trace_metadata():
    runtime = ResumeAdvisorToolRuntime()

    result = runtime.execute(
        name="parse_jd_requirements",
        user_id="u1",
        session_id="advisor-1",
        trace_id="tr-1",
        arguments={"jdText": "需要 FastAPI"},
        handler=lambda: {"requirements": ["FastAPI"]},
    )

    assert result["ok"] is True
    assert result["data"] == {"requirements": ["FastAPI"]}
    assert result["meta"]["traceId"] == "tr-1"
    assert result["meta"]["sideEffect"] == "read"


def test_advisor_tool_runtime_rejects_invalid_domain_output():
    result = ResumeAdvisorToolRuntime().execute(
        name="extract_jd_requirements",
        user_id="u1",
        session_id="advisor-1",
        trace_id="tr-1",
        arguments={"jdText": "需要 FastAPI"},
        handler=lambda: {"requirements": "FastAPI"},
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
