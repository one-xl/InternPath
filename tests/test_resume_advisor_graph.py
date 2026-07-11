from __future__ import annotations

from datetime import datetime, timedelta

from backend.resume_advisor.graph import ResumeAdvisorGraph
from backend.resume_advisor.langgraph import LangGraphResumeAdvisor
from backend.resume_advisor.verification import QualityReviewResult, SuggestionDraft
from langgraph.checkpoint.memory import InMemorySaver


class _Repository:
    def __init__(self, blocks):
        self.blocks = blocks
        self.suggestions = []
        self.turns = []
        self.events = []
        self.facts = []
        self.session_status = "ACTIVE"
        self.run_status = "QUEUED"
        self.run_created_at = datetime.now() - timedelta(milliseconds=180)
        self.run_started_at = datetime.now()
        self.telemetry: dict[str, object] = {}

    def get_session(self, _user_id, _session_id):
        return {"id": "session-1", "jdText": "需要 FastAPI 和 Redis 经验"}

    def update_run(self, **kwargs):
        self.run_status = kwargs["status"]

    def get_run(self, **_kwargs):
        return {
            "createdAt": self.run_created_at,
            "startedAt": self.run_started_at,
            "telemetry": self.telemetry,
        }

    def merge_run_telemetry(self, **kwargs):
        self.telemetry.update(kwargs["telemetry"])

    def append_event(self, **kwargs):
        self.events.append(kwargs)

    def get_resume_view(self, _user_id, _session_id):
        return {"blocks": self.blocks}

    def list_suggestions(self, _user_id, _session_id):
        return self.suggestions

    def list_turns(self, _user_id, _session_id):
        return self.turns

    def list_confirmed_facts(self, _user_id, _session_id):
        return self.facts

    def create_suggestion(self, **kwargs):
        item = {"id": f"sug-{len(self.suggestions) + 1}", **kwargs["data"]}
        self.suggestions.append(item)
        return item

    def update_suggestion_status(self, _user_id, suggestion_id, status):
        for suggestion in self.suggestions:
            if suggestion["id"] == suggestion_id:
                suggestion["status"] = status
                return

    def append_turn(self, **kwargs):
        item = {"id": f"turn-{len(self.turns) + 1}", **kwargs}
        self.turns.append(item)
        return item

    def update_session(self, _user_id, _session_id, **kwargs):
        self.session_status = kwargs["session_status"]


def test_graph_creates_evidence_bound_copyable_suggestion_without_jd_as_fact():
    repository = _Repository(
        [
            {
                "id": "block-1",
                "kind": "bullet",
                "sectionId": "project_experience",
                "sectionName": "项目经历",
                "itemLabel": "第 1 条",
                "text": "负责 FastAPI 接口开发",
                "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条",
                "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-1")

    assert result["status"] == "WAITING_FOR_USER"
    suggestion = repository.suggestions[0]
    assert suggestion["resumeEvidenceBlockIds"] == ["block-1"]
    assert suggestion["factStatus"] == "supported"
    assert suggestion["copyText"] == "• 负责 FastAPI 接口开发"
    assert "Redis" not in suggestion["copyText"]
    assert repository.run_status == "PAUSED"


def test_graph_publishes_real_model_deltas_before_the_final_suggestion(monkeypatch):
    repository = _Repository(
        [
            {
                "id": "block-stream", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-stream",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    decode_options: list[bool] = []

    def fake_decode(**kwargs):
        decode_options.append(bool(kwargs.get("allow_model_call")))
        kwargs["on_cache_event"]("resume_advisor_jd_decode_v1", False)
        return ["FastAPI"]

    def fake_draft(**kwargs):
        kwargs["on_cache_event"]("resume_advisor_draft_v1", False)
        kwargs["on_provider_usage"](
            "resume_copywriter",
            {"providerCacheAvailable": True, "providerCacheHit": True, "providerCachedTokens": 128},
        )
        kwargs["on_delta"]("• 使用")
        assert repository.events[-1]["event_type"] == "model_delta"
        assert repository.events[-1]["payload"]["delta"] == "• 使用"
        kwargs["on_delta"](" FastAPI 开发接口")
        return SuggestionDraft(
            proposed_text="• 使用 FastAPI 开发接口",
            issue="提升可扫描性",
            rationale="保留已有事实",
            expected_impact="更易阅读",
            priority="high",
        )

    monkeypatch.setattr("backend.resume_advisor.graph.decode_jd_requirements", fake_decode)
    monkeypatch.setattr("backend.resume_advisor.graph.draft_resume_suggestion", fake_draft)
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_with_hr_critic",
        lambda **_kwargs: QualityReviewResult(is_passed=True, score=95, issues=[], reviewer="hr_critic"),
    )

    model_client = type("StreamingClient", (), {})()
    model_client._internpath_provider_first_token_ms = 123
    result = ResumeAdvisorGraph(repository, model_client=model_client, model_id="gpt-test").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-stream",
    )

    event_types = [event["event_type"] for event in repository.events]
    streamed_text = "".join(
        str(event.get("payload", {}).get("delta") or "")
        for event in repository.events
        if event["event_type"] == "model_delta"
    )
    assert result["status"] == "WAITING_FOR_USER"
    assert decode_options == [False]
    assert streamed_text == "• 使用 FastAPI 开发接口"
    assert event_types.index("model_delta") < event_types.index("suggestion")
    first_delta = next(event for event in repository.events if event["event_type"] == "model_delta")
    first_payload = first_delta["payload"]
    assert first_payload["providerFirstTokenMs"] == 123
    assert first_payload["queueMs"] >= 0
    assert first_payload["endToEndFirstTokenMs"] >= first_payload["queueMs"]
    assert first_payload["firstTokenSloMs"] == 10_000
    assert first_payload["firstTokenSloMet"] is True
    assert repository.telemetry == {
        key: first_payload[key]
        for key in (
            "firstTokenMs",
            "providerFirstTokenMs",
            "queueMs",
            "endToEndFirstTokenMs",
            "firstTokenSloMs",
            "firstTokenSloMet",
        )
    }
    tool_calls = [event["payload"]["toolName"] for event in repository.events if event["event_type"] == "tool_call"]
    tool_results = [event["payload"]["toolName"] for event in repository.events if event["event_type"] == "tool_result"]
    assert tool_calls == ["extract_jd_requirements", "verify_suggestion_facts", "hr_quality_review"]
    assert tool_results == tool_calls
    provider_event = next(event for event in repository.events if event["event_type"] == "provider_usage")
    assert provider_event["payload"]["providerCacheHit"] is True
    assert provider_event["payload"]["providerCachedTokens"] == 128


def test_graph_does_not_create_copyable_suggestion_when_fact_gate_requires_evidence(monkeypatch):
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    graph = ResumeAdvisorGraph(repository)
    monkeypatch.setattr(graph, "_draft_copy", lambda _text: "• 主导 Redis 缓存架构，使接口性能提升 30%")

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-fact-gate")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "question"
    assert repository.turns[-1]["payload"]["questionKey"].startswith("fact:")


def test_graph_does_not_create_copyable_suggestion_when_quality_gate_fails(monkeypatch):
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    graph = ResumeAdvisorGraph(repository)
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_with_hr_critic",
        lambda **_kwargs: QualityReviewResult(
            is_passed=False,
            score=60,
            issues=["模型审查认为表达仍需调整"],
            reviewer="hr_critic",
        ),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-quality-gate")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["payload"]["quality"]["is_passed"] is False
    assert "模型审查认为表达仍需调整" in repository.turns[-1]["payload"]["quality"]["issues"]
    assert repository.turns[-1]["payload"]["target"]["locationLabel"] == "项目经历 > 第 1 条"


def test_graph_requires_explicit_user_confirmation_when_no_more_blocks_remain():
    repository = _Repository([])

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-1")

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.session_status == "READY_FOR_CONFIRMATION"
    assert repository.run_status == "COMPLETED"


def test_graph_revises_a_suggestion_as_a_new_version_instead_of_overwriting_history():
    block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
        "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
    }
    repository = _Repository([block])
    repository.suggestions.append({"id": "sug-previous", "status": "needs_revision", "target": {"blockId": "block-1"}})

    ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-2")

    assert repository.suggestions[-1]["parentSuggestionId"] == "sug-previous"
    assert repository.suggestions[-1]["id"] != "sug-previous"


def test_graph_answers_a_follow_up_question_before_moving_to_the_next_resume_block():
    first_block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
        "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
    }
    second_block = {**first_block, "id": "block-2", "text": "维护 Redis 缓存", "textHash": "hash-2", "itemLabel": "第 2 条"}
    repository = _Repository([first_block, second_block])
    repository.suggestions.append({
        "id": "sug-1", "status": "proposed", "target": {"blockId": "block-1", "locationLabel": "项目经历 > 第 1 条"},
        "originalText": first_block["text"], "proposedText": "• 负责 FastAPI 接口开发", "rationale": "保留事实并提升可扫描性。",
    })
    repository.turns.extend([
        {"id": "turn-suggestion", "role": "assistant", "content": "请查看建议卡。", "messageKind": "suggestion", "payload": {"suggestionId": "sug-1"}},
        {"id": "turn-question", "role": "user", "content": "为什么这样改？", "messageKind": "text", "payload": {}},
    ])

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-follow-up")

    assert result["status"] == "WAITING_FOR_USER"
    assert len(repository.suggestions) == 1
    assert repository.turns[-1]["message_kind"] == "text"
    assert "项目经历 > 第 1 条" in repository.turns[-1]["content"]


def test_graph_treats_a_free_form_revision_request_as_a_new_version_of_the_active_suggestion():
    first_block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发；协助编写接口测试", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
        "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
    }
    second_block = {**first_block, "id": "block-2", "text": "维护 Redis 缓存", "textHash": "hash-2", "itemLabel": "第 2 条"}
    repository = _Repository([first_block, second_block])
    repository.suggestions.append({
        "id": "sug-1", "status": "proposed", "target": {"blockId": "block-1", "locationLabel": "项目经历 > 第 1 条"},
        "originalText": first_block["text"], "proposedText": "• 负责 FastAPI 接口开发；协助编写接口测试", "rationale": "保留事实并提升可扫描性。",
    })
    repository.turns.append({"id": "turn-revision", "role": "user", "content": "请改短一点", "messageKind": "text", "payload": {}})

    ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-free-form-revision")

    assert repository.suggestions[0]["status"] == "needs_revision"
    assert repository.suggestions[-1]["parentSuggestionId"] == "sug-1"
    assert repository.suggestions[-1]["target"]["blockId"] == "block-1"


def test_graph_applies_a_conservative_local_shorten_request_to_a_new_version():
    block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发；协助编写接口测试", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
        "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
    }
    repository = _Repository([block])
    repository.suggestions.append({"id": "sug-previous", "status": "needs_revision", "target": {"blockId": "block-1"}})
    repository.turns.append({
        "id": "turn-feedback", "role": "user", "content": "请改短一点，保留所有可核验事实。",
        "payload": {"suggestionId": "sug-previous", "action": "needs_revision"},
    })

    ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-shorten")

    assert repository.suggestions[-1]["proposedText"] == "• 负责 FastAPI 接口开发"


def test_graph_asks_one_evidence_question_after_an_applied_suggestion():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    repository.suggestions.append({"id": "sug-applied", "status": "applied", "target": {"blockId": "block-1"}})

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-3")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.turns[-1]["message_kind"] == "question"
    assert repository.turns[-1]["payload"]["questionKey"].startswith("requirement:")


def test_graph_does_not_repeat_a_question_or_suggestion_after_user_denies_it():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    repository.facts = [{"claimKey": "fact:block-1:Redis", "claimValue": "没有 Redis 相关真实经历", "status": "denied"}]

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-denied")

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.suggestions == []


def test_langgraph_wrapper_persists_a_pause_after_presenting_a_suggestion():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )

    result = LangGraphResumeAdvisor(repository, checkpointer=InMemorySaver()).run(user_id="u1", session_id="session-1", run_id="run-langgraph")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.run_status == "PAUSED"


def test_langgraph_wrapper_resumes_the_interrupted_session_with_command():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate",
                "locator": {"sourceFormat": "docx", "lineStart": 4, "lineEnd": 4},
            }
        ]
    )
    graph = LangGraphResumeAdvisor(repository, checkpointer=InMemorySaver())
    graph.run(user_id="u1", session_id="session-1", run_id="run-langgraph")
    repository.suggestions[0]["status"] = "applied"

    result = graph.resume(user_id="u1", session_id="session-1", payload={"messageId": "turn-2"})

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.turns[-1]["message_kind"] == "question"
