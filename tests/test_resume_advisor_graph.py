from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.agents.rag_evidence_reviewer import RagEvidenceReview
import backend.resume_advisor.verification as advisor_verification
from backend.resume_advisor.graph import ResumeAdvisorGraph
from backend.resume_advisor.langgraph import LangGraphResumeAdvisor
from backend.resume_advisor.verification import (
    HRCriticInvalidOutputError,
    HRCriticProviderError,
    HRCriticUnavailableError,
    QualityReviewResult,
    SuggestionDraft,
)
from langgraph.checkpoint.memory import InMemorySaver


_TEST_MODEL_CLIENT = object()


def _configured_graph(repository):
    return ResumeAdvisorGraph(repository, model_client=_TEST_MODEL_CLIENT, model_id="test-model")


def _configured_model_provider(_user_id):
    return _TEST_MODEL_CLIENT, "test-model"


def _hr_review_payload(*, failed_dimension: str | None = None) -> dict[str, object]:
    dimensions = {
        name: {
            "verdict": "fail" if name == failed_dimension else "pass",
            "rationale": f"{name} 审核结论。",
            "evidence_basis": ["负责 FastAPI 接口开发"],
        }
        for name in (
            "factual_fidelity",
            "role_jd_relevance",
            "clarity_scannability",
            "recruiting_usefulness",
        )
    }
    return {
        "score": 95 if failed_dimension is None else 60,
        "is_passed": failed_dimension is None,
        **dimensions,
        "critique": "模型审核结论。",
        "suggestions": "模型给出的下一步建议。",
    }


def _hr_review_result(*, failed_dimension: str | None = None) -> QualityReviewResult:
    review = _hr_review_payload(failed_dimension=failed_dimension)
    return QualityReviewResult(
        is_passed=bool(review["is_passed"]),
        score=int(review["score"]),
        issues=[] if review["is_passed"] else [str(review["critique"])],
        reviewer="hr_critic",
        hr_review=review,
    )


@pytest.fixture(autouse=True)
def _stub_configured_model_path(monkeypatch):
    cache: dict[str, object] = {}

    def fake_draft(*, original_text: str, **_kwargs):
        copy_text = original_text.strip()
        if copy_text.startswith(("• ", "- ", "· ", "* ")):
            copy_text = copy_text[2:].strip()
        return SuggestionDraft(
            proposed_text=f"岗位相关经历：{copy_text}" if copy_text else copy_text,
            issue="根据岗位要求提升已有事实的可扫描性。",
            rationale="由配置模型生成，并要求后续经过独立事实与质量门。",
            expected_impact="更清晰地呈现与岗位相关的既有职责。",
            priority="high",
        )

    monkeypatch.setattr("backend.resume_advisor.graph.draft_resume_suggestion", fake_draft)
    monkeypatch.setattr(
        "backend.resume_advisor.verification.get_agent_cache",
        lambda _namespace, key: cache.get(key),
    )
    monkeypatch.setattr(
        "backend.resume_advisor.verification.set_agent_cache",
        lambda _namespace, key, value: cache.setdefault(key, value),
    )
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_with_hr_critic",
        lambda **_kwargs: _hr_review_result(),
    )
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_rag_evidence",
        lambda *, candidates, **_kwargs: RagEvidenceReview(
            selected_chunk_ids=[str(item.get("id") or item.get("chunkId") or "") for item in candidates],
            relevance_summary="测试模型已从检索结果选择可归因证据。",
            uncovered_requirements=[],
        ),
    )
    monkeypatch.setattr(
        "backend.resume_advisor.graph.decode_jd_requirements",
        lambda *, fallback_requirements, **_kwargs: fallback_requirements,
    )

    def fake_hybrid_search(_self, *, documents, **_kwargs):
        return {
            "strategy": "hybrid",
            "semanticMode": "embedding",
            "results": [
                {
                    "documentId": document.get("documentId", "resume"),
                    "chunkId": document.get("chunkId", document.get("id", "")),
                    "text": document.get("content", ""),
                    "sectionTitle": document.get("sectionTitle", "简历内容"),
                    "metadata": document.get("metadata", {}),
                }
                for document in documents[:6]
            ],
        }

    monkeypatch.setattr("ai_service_client.AiServiceClient.rag_search", fake_hybrid_search)


class _Repository:
    def __init__(self, blocks):
        self.blocks = blocks
        self.suggestions = []
        self.turns = []
        self.events = []
        self.facts = []
        self.session_status = "ACTIVE"
        self.run_status = "QUEUED"
        self.cancelled = False
        self.run_created_at = datetime.now() - timedelta(milliseconds=180)
        self.run_started_at = datetime.now()
        self.telemetry: dict[str, object] = {}

    def get_session(self, _user_id, _session_id):
        return {"id": "session-1", "jdText": "需要 FastAPI 和 Redis 经验"}

    def update_run(self, **kwargs):
        self.run_status = kwargs["status"]

    def is_run_cancelled(self, **_kwargs):
        return self.cancelled

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

    result = _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-1")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.turns[0]["message_kind"] == "resume_scan"
    assert repository.turns[0]["payload"]["jdCoverage"]["matchedRequirements"] == ["FastAPI"]
    assert repository.turns[0]["payload"]["jdCoverage"]["missingRequirements"] == ["Redis"]
    suggestion = repository.suggestions[0]
    assert suggestion["resumeEvidenceBlockIds"] == ["block-1"]
    assert suggestion["factStatus"] == "supported"
    assert suggestion["copyText"] == "岗位相关经历：负责 FastAPI 接口开发"
    assert "Redis" not in suggestion["copyText"]
    assert repository.run_status == "PAUSED"


def test_graph_shows_agent_authored_alignment_feedback_without_creating_a_diff(monkeypatch):
    block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high", "locator": {"sourceFormat": "txt"},
    }
    repository = _Repository([block])
    graph = _configured_graph(repository)
    hr_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_with_hr_critic",
        lambda **kwargs: hr_calls.append(kwargs) or _hr_review_result(),
    )
    monkeypatch.setattr(
        graph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: SuggestionDraft(
            outcome="affirmation",
            proposed_text="",
            issue="岗位匹配检查",
            rationale="模型基于 RAG 证据完成判断。",
            expected_impact="无需改写。",
            priority="low",
            affirmation="项目经历 > 第 1 条已经清楚说明负责 FastAPI 接口开发，这与岗位的核心技术要求匹配。",
            highlight_locations=["项目经历 > 第 1 条"],
        ),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-affirmation")

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "text"
    assert repository.turns[-1]["content"].startswith("项目经历 > 第 1 条")
    assert repository.turns[-1]["payload"]["mode"] == "alignment_assessment"
    assert repository.turns[-1]["payload"]["highlightLocations"] == ["项目经历 > 第 1 条"]
    assert hr_calls and hr_calls[0]["proposed_text"].startswith("项目经历 > 第 1 条")


def test_graph_persists_all_suggestion_display_fields_from_resume_copywriter(monkeypatch):
    block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
        "locator": {"sourceFormat": "txt"},
    }
    repository = _Repository([block])
    agent_calls: list[dict[str, object]] = []
    agent_output = {
        "proposed_text": "岗位相关经历：负责 FastAPI 接口开发",
        "issue": "模型问题字段",
        "rationale": "模型理由字段",
        "expected_impact": "模型影响字段",
        "priority": "low",
    }

    class FakeResumeCopywriter:
        def __init__(self, **_kwargs):
            pass

        async def generate_advisor_suggestion(self, **kwargs):
            agent_calls.append(kwargs)
            return agent_output

    monkeypatch.setattr(
        "backend.agents.resume_copywriter.ResumeCopywriter",
        FakeResumeCopywriter,
    )
    monkeypatch.setattr(
        "backend.resume_advisor.graph.draft_resume_suggestion",
        advisor_verification.draft_resume_suggestion,
    )

    result = _configured_graph(repository).run(
        user_id="u1",
        session_id="session-1",
        run_id="run-structured-copywriter",
    )

    assert result["status"] == "WAITING_FOR_USER"
    suggestion = repository.suggestions[0]
    assert {
        "proposedText": suggestion["proposedText"],
        "issue": suggestion["issue"],
        "rationale": suggestion["rationale"],
        "expectedImpact": suggestion["expectedImpact"],
        "priority": suggestion["priority"],
    } == {
        "proposedText": agent_output["proposed_text"],
        "issue": agent_output["issue"],
        "rationale": agent_output["rationale"],
        "expectedImpact": agent_output["expected_impact"],
        "priority": agent_output["priority"],
    }
    assert "修改建议工作区" in repository.turns[-1]["content"]
    assert repository.turns[-1]["message_kind"] == "text"
    assert agent_calls[0]["original_content"] == block["text"]


def test_graph_stops_before_retrieval_when_no_model_is_configured(monkeypatch):
    repository = _Repository([
        {
            "id": "block-1",
            "kind": "bullet",
            "sectionId": "project_experience",
            "sectionName": "Project",
            "itemLabel": "item 1",
            "text": "Developed FastAPI API",
            "textHash": "hash-1",
            "locationLabel": "Project > item 1",
            "locatorConfidence": "high",
            "locator": {"sourceFormat": "txt"},
        }
    ])

    monkeypatch.setattr(
        "backend.resume_advisor.graph.decode_jd_requirements",
        advisor_verification.decode_jd_requirements,
    )

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-no-model")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["payload"]["mode"] == "jd_requirements"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unavailable"
    assert repository.turns[-1]["payload"]["errorCode"] == "resume_advisor_jd_requirements_unavailable"
    assert repository.turns[-1]["content"] == ""
    assert not any(event["event_type"] == "suggestion" for event in repository.events)


def test_graph_prioritizes_relevant_project_evidence_and_never_rewrites_personal_details():
    repository = _Repository(
        [
            {
                "id": "contact", "kind": "paragraph", "sectionId": "contact", "sectionName": "基本信息",
                "itemLabel": "第 1 条", "text": "区泽康 15820246683 example@example.com", "textHash": "contact",
                "locationLabel": "基本信息 > 第 1 条", "locatorConfidence": "high", "locator": {"sourceFormat": "docx"},
            },
            {
                "id": "summary", "kind": "paragraph", "sectionId": "self_introduction", "sectionName": "自我评价",
                "itemLabel": "第 1 条", "text": "区泽康", "textHash": "summary", "locationLabel": "自我评价 > 第 1 条",
                "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
            },
            {
                "id": "course", "kind": "paragraph", "sectionId": "coursework", "sectionName": "核心课程",
                "itemLabel": "第 1 条", "text": "软件工程、数据库系统原理", "textHash": "course", "locationLabel": "核心课程 > 第 1 条",
                "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
            },
            {
                "id": "project", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "使用 FastAPI 开发实习管理接口", "textHash": "project", "locationLabel": "项目经历 > 第 1 条",
                "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
            },
        ]
    )

    result = _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-priority")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions[0]["target"]["blockId"] == "project"
    assert repository.suggestions[0]["target"]["sectionId"] == "project_experience"


def test_graph_does_not_ask_a_script_generated_question_for_an_unrelated_block():
    repository = _Repository(
        [
            {
                "id": "project", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "协助整理业务需求并编写测试用例", "textHash": "project",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
            }
        ]
    )

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-gap")

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "completion"


def test_graph_can_improve_coursework_in_a_docx_table_cell():
    repository = _Repository(
        [
            {
                "id": "course-table", "kind": "table_cell", "sectionId": "coursework", "sectionName": "核心课程",
                "itemLabel": "第 1 条", "text": "Python Web 开发 | FastAPI 接口设计", "textHash": "course-table",
                "locationLabel": "核心课程 > 第 1 条", "locatorConfidence": "high", "locator": {"sourceFormat": "docx", "tableIndex": 0},
            }
        ]
    )

    result = _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-course-table")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions[0]["target"]["blockId"] == "course-table"


def test_graph_links_a_confirmed_user_fact_when_it_supports_the_rewrite(monkeypatch):
    block = {
        "id": "project", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "project",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
    }
    repository = _Repository([block])
    repository.facts = [{
        "id": "fact-redis", "claimKey": "requirement:redis", "claimValue": "我曾使用 Redis 缓存热点查询。",
        "status": "confirmed", "scope": "session",
    }]
    graph = _configured_graph(repository)
    monkeypatch.setattr(
        graph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: SuggestionDraft(
            proposed_text="• 使用 FastAPI 开发接口，并使用 Redis 缓存热点查询",
            issue="根据岗位要求提升已有事实的可扫描性。",
            rationale="由配置模型生成。",
            expected_impact="更清晰地呈现已有职责。",
            priority="high",
        ),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-user-fact")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions[0]["factStatus"] == "supported"
    assert repository.suggestions[0]["userFactIds"] == ["fact-redis"]


def test_graph_stops_before_any_agent_action_when_the_run_was_cancelled():
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
    repository.cancelled = True

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-cancelled")

    assert result == {"status": "CANCELLED"}
    assert repository.suggestions == []
    assert repository.events[-1]["event_type"] == "run_cancelled"


def test_graph_stops_before_model_call_when_cancellation_arrives_after_jd_parsing(monkeypatch):
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

    def cancel_after_jd_parse(**_kwargs):
        repository.cancelled = True
        return ["FastAPI"]

    monkeypatch.setattr("backend.resume_advisor.graph.decode_jd_requirements", cancel_after_jd_parse)
    monkeypatch.setattr(
        ResumeAdvisorGraph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model must not run after cancellation")),
    )

    result = ResumeAdvisorGraph(repository).run(user_id="u1", session_id="session-1", run_id="run-cancel-after-jd")

    assert result == {"status": "CANCELLED"}
    assert repository.suggestions == []


def test_graph_quarantines_model_deltas_until_the_suggestion_is_approved(monkeypatch):
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
        kwargs["on_cache_event"]("resume_advisor_draft_v2", False)
        kwargs["on_provider_usage"](
            "resume_copywriter",
            {"providerCacheAvailable": True, "providerCacheHit": True, "providerCachedTokens": 128},
        )
        kwargs["on_delta"]("• 使用")
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
        lambda **_kwargs: _hr_review_result(),
    )

    model_client = type("StreamingClient", (), {})()
    model_client._internpath_provider_first_token_ms = 123
    result = ResumeAdvisorGraph(repository, model_client=model_client, model_id="gpt-test").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-stream",
    )

    event_types = [event["event_type"] for event in repository.events]
    assert result["status"] == "WAITING_FOR_USER"
    assert decode_options == [True]
    assert "model_delta" not in event_types
    tool_calls = [event["payload"]["toolName"] for event in repository.events if event["event_type"] == "tool_call"]
    tool_results = [event["payload"]["toolName"] for event in repository.events if event["event_type"] == "tool_result"]
    assert tool_calls == [
        "extract_jd_requirements",
        "retrieve_resume_evidence",
        "review_rag_evidence",
        "verify_suggestion_facts",
        "hr_quality_review",
    ]
    assert tool_results == tool_calls
    jd_result = next(
        event for event in repository.events
        if event["event_type"] == "tool_result" and event["payload"]["toolName"] == "extract_jd_requirements"
    )
    assert jd_result["payload"]["summary"]["requirementCount"] == 1
    assert "requirements" not in jd_result["payload"]["summary"]
    provider_event = next(event for event in repository.events if event["event_type"] == "provider_usage")
    assert provider_event["payload"]["providerCacheHit"] is True
    assert provider_event["payload"]["providerCachedTokens"] == 128


def test_graph_prefers_ai_service_hybrid_rag_and_keeps_source_block_provenance():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
                "locator": {"sourceFormat": "txt"},
            }
        ]
    )
    repository.get_resume_view = lambda _user_id, _session_id: {
        "blocks": repository.blocks,
        "chunks": [
            {
                "id": "chunk-1",
                "documentId": "resume-file-1",
                "content": "负责 FastAPI 接口开发",
                "section": "项目经历",
                "sectionType": "project_experience",
                "semanticType": "experience",
                "importance": 0.9,
                "embedding": [1.0, 0.0],
                "sourceBlockIds": ["block-1"],
                "metadata": {"sourceBlockIds": ["block-1"]},
            }
        ],
    }

    class _HybridClient:
        def __init__(self):
            self.calls = []

        def rag_search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "strategy": "hybrid",
                "semanticMode": "embedding",
                "results": [
                    {
                        "documentId": "resume-file-1",
                        "chunkId": "chunk-1",
                        "text": "负责 FastAPI 接口开发",
                        "sectionTitle": "项目经历",
                        "metadata": {"sourceBlockIds": ["block-1"]},
                    }
                ],
            }

    client = _HybridClient()
    graph = ResumeAdvisorGraph(
        repository,
        model_client=_TEST_MODEL_CLIENT,
        model_id="test-model",
        ai_service_client=client,
    )
    result = graph.run(user_id="u1", session_id="session-1", run_id="run-hybrid-rag")

    assert result["status"] == "WAITING_FOR_USER"
    assert client.calls and client.calls[0]["strategy"] == "hybrid"
    document = client.calls[0]["documents"][0]
    assert document["embedding"] == [1.0, 0.0]
    assert document["metadata"]["sourceBlockIds"] == ["block-1"]
    assert repository.telemetry["resumeRetrieval"] == {
        "mode": "ai_service_hybrid",
        "semanticMode": "embedding",
        "evidenceCount": 1,
    }
    assert repository.suggestions[0]["resumeEvidenceBlockIds"] == ["block-1"]
    tool_result = next(
        event for event in repository.events
        if event["event_type"] == "tool_result" and event["payload"]["toolName"] == "retrieve_resume_evidence"
    )
    assert tool_result["payload"]["summary"]["retrievalMode"] == "ai_service_hybrid"
    assert tool_result["payload"]["summary"]["semanticMode"] == "embedding"


def test_graph_stops_without_a_suggestion_when_rag_reviewer_finds_no_evidence(monkeypatch):
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "参与 FastAPI 接口的需求讨论", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high", "locator": {"sourceFormat": "txt"},
            }
        ]
    )
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_rag_evidence",
        lambda **_kwargs: RagEvidenceReview(
            selected_chunk_ids=[],
            relevance_summary="没有候选片段能证明 JD 所需的 FastAPI 经历。",
            uncovered_requirements=["FastAPI"],
        ),
    )

    result = _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-no-rag-evidence")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["payload"]["mode"] == "rag_evidence_insufficient"
    assert "FastAPI" in repository.turns[-1]["content"]


def test_graph_adds_selected_project_knowledge_to_advisor_rag(monkeypatch):
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
                "locator": {"sourceFormat": "txt"},
            }
        ]
    )
    repository.turns = [
        {
            "payload": {
                "projectKnowledgeScope": "selected",
                "projectKnowledgeDocumentIds": [42],
            }
        }
    ]
    requested_selection: dict[str, object] = {}

    class _HybridClient:
        def __init__(self):
            self.calls = []

        def rag_search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "strategy": "hybrid",
                "semanticMode": "embedding",
                "results": [
                    {
                        "documentId": "resume",
                        "chunkId": "resume-block-1",
                        "text": "负责 FastAPI 接口开发",
                        "sectionTitle": "项目经历",
                        "metadata": {"sourceBlockIds": ["block-1"]},
                    }
                ],
            }

    client = _HybridClient()
    graph = ResumeAdvisorGraph(
        repository,
        model_client=_TEST_MODEL_CLIENT,
        model_id="test-model",
        ai_service_client=client,
    )

    def project_chunks(*, user_id, scope, document_ids):
        requested_selection.update({"user_id": user_id, "scope": scope, "document_ids": document_ids})
        return [
            {
                "id": "project:42:chunk-1",
                "documentId": "42",
                "chunkId": "chunk-1",
                "content": "InternPath 项目使用 Redis 缓存与 FastAPI 构建异步任务队列。",
                "section": "InternPath 项目",
                "sectionType": "project_experience",
                "semanticType": "experience",
                "importance": 0.9,
                "sourceType": "project",
                "metadata": {"sourceType": "project", "documentId": "42"},
            }
        ]

    monkeypatch.setattr(graph, "_project_chunks_for_retrieval", project_chunks)

    result = graph.run(user_id="u-project-rag", session_id="session-1", run_id="run-project-rag")

    assert result["status"] == "WAITING_FOR_USER"
    assert requested_selection == {
        "user_id": "u-project-rag",
        "scope": "selected",
        "document_ids": [42],
    }
    project_document = next(document for document in client.calls[0]["documents"] if document["documentId"] == "42")
    assert project_document["metadata"]["sourceType"] == "project"


def test_graph_stops_when_hybrid_embedding_retrieval_is_unavailable():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
                "locator": {"sourceFormat": "txt"},
            }
        ]
    )

    class _NoEmbeddingClient:
        def rag_search(self, **_kwargs):
            return {"strategy": "hybrid", "semanticMode": "lexical_fallback", "results": []}

    graph = ResumeAdvisorGraph(
        repository,
        model_client=_TEST_MODEL_CLIENT,
        model_id="test-model",
        ai_service_client=_NoEmbeddingClient(),
    )
    result = graph.run(user_id="u1", session_id="session-1", run_id="run-local-rag-fallback")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["payload"]["mode"] == "resume_retrieval"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unavailable"


def test_graph_stops_when_ai_service_returns_an_invalid_response():
    repository = _Repository(
        [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
                "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
                "locator": {"sourceFormat": "txt"},
            }
        ]
    )

    class _InvalidResponseClient:
        def rag_search(self, **_kwargs):
            return []

    graph = ResumeAdvisorGraph(
        repository,
        model_client=_TEST_MODEL_CLIENT,
        model_id="test-model",
        ai_service_client=_InvalidResponseClient(),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-invalid-rag-response")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["payload"]["mode"] == "resume_retrieval"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unavailable"


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
    graph = _configured_graph(repository)
    hr_calls = 0

    def fail_if_hr_review_runs(**_kwargs):
        nonlocal hr_calls
        hr_calls += 1
        raise AssertionError("HRCritic must run only after fact verification passes")

    monkeypatch.setattr("backend.resume_advisor.graph.review_with_hr_critic", fail_if_hr_review_runs)
    monkeypatch.setattr(
        graph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: SuggestionDraft(
            proposed_text="• 主导 Redis 缓存架构，使接口性能提升 30%",
            issue="根据岗位要求提升已有事实的可扫描性。",
            rationale="由配置模型生成。",
            expected_impact="更清晰地呈现已有职责。",
            priority="high",
        ),
    )
    monkeypatch.setattr(
        graph,
        "_request_evidence_clarification",
        lambda **_kwargs: ("请确认项目经历中是否有 Redis 缓存和性能结果；直接在聊天框补充即可。", "ok", None),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-fact-gate")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "text"
    assert "Redis 缓存" in repository.turns[-1]["content"]
    assert "block-1" not in repository.turns[-1]["content"]
    assert repository.turns[-1]["payload"]["mode"] == "evidence_clarification"
    assert hr_calls == 0
    assert not any(event["event_type"] == "model_delta" for event in repository.events)


def test_graph_does_not_persist_a_jd_only_chinese_responsibility_as_a_suggestion(monkeypatch):
    block = {
        "id": "block-1", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
        "itemLabel": "第 1 条", "text": "负责 FastAPI 接口开发", "textHash": "hash-1",
        "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "high",
        "locator": {"sourceFormat": "txt"},
    }
    repository = _Repository([block])
    repository.get_session = lambda _user_id, _session_id: {
        "id": "session-1",
        "jdText": "岗位要求主要负责跨部门需求协调",
    }
    graph = _configured_graph(repository)
    monkeypatch.setattr(
        graph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: SuggestionDraft(
            proposed_text="• 主要负责跨部门需求协调",
            issue="模型建议",
            rationale="模型生成。",
            expected_impact="更清晰。",
            priority="high",
        ),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-jd-only-responsibility")

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "completion"


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
    graph = _configured_graph(repository)
    monkeypatch.setattr(
        "backend.resume_advisor.graph.review_with_hr_critic",
        lambda **_kwargs: _hr_review_result(failed_dimension="clarity_scannability"),
    )

    result = graph.run(user_id="u1", session_id="session-1", run_id="run-quality-gate")

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["payload"]["quality"]["is_passed"] is False
    assert "模型审核结论。" in repository.turns[-1]["payload"]["quality"]["issues"]
    assert repository.turns[-1]["payload"]["target"]["locationLabel"] == "项目经历 > 第 1 条"
    assert not any(event["event_type"] == "model_delta" for event in repository.events)


@pytest.mark.parametrize(
    ("review_error", "model_status"),
    [
        (HRCriticUnavailableError("no configured reviewer"), "unavailable"),
        (HRCriticProviderError("provider unavailable"), "failed"),
        (HRCriticInvalidOutputError("missing review dimensions"), "invalid_output"),
    ],
)
def test_graph_does_not_release_a_suggestion_when_hr_review_cannot_be_trusted(
    monkeypatch,
    review_error,
    model_status,
):
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

    def failed_review(**_kwargs):
        raise review_error

    monkeypatch.setattr("backend.resume_advisor.graph.review_with_hr_critic", failed_review)

    result = _configured_graph(repository).run(
        user_id="u1",
        session_id="session-1",
        run_id=f"run-hr-{model_status}",
    )

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.suggestions == []
    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["content"] == ""
    assert repository.turns[-1]["payload"]["mode"] == "hr_quality_review"
    assert repository.turns[-1]["payload"]["modelStatus"] == model_status
    assert repository.turns[-1]["payload"]["errorCode"] == f"resume_advisor_hr_quality_review_{model_status}"
    review_tool_result = next(
        event
        for event in reversed(repository.events)
        if event["event_type"] == "tool_result" and event["payload"]["toolName"] == "hr_quality_review"
    )
    assert review_tool_result["payload"]["ok"] is False
    assert not any(event["event_type"] == "suggestion" for event in repository.events)
    assert not any(event["event_type"] == "model_delta" for event in repository.events)


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

    _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-2")

    assert repository.suggestions[-1]["parentSuggestionId"] == "sug-previous"
    assert repository.suggestions[-1]["id"] != "sug-previous"


def test_graph_answers_a_follow_up_question_before_moving_to_the_next_resume_block(monkeypatch):
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

    model_reply = "原文已经写明 FastAPI，改写只是把已有职责放在更容易看到的位置。"
    agent_calls: list[dict[str, object]] = []

    async def fake_explain(_self, **kwargs):
        agent_calls.append(kwargs)
        return model_reply

    monkeypatch.setattr(
        "backend.agents.resume_copywriter.ResumeCopywriter.explain_advisor_suggestion",
        fake_explain,
    )
    result = ResumeAdvisorGraph(repository, model_client=object(), model_id="configured-model").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-follow-up",
    )

    assert result["status"] == "WAITING_FOR_USER"
    assert len(repository.suggestions) == 1
    assert repository.turns[-1]["message_kind"] == "text"
    assert repository.turns[-1]["content"] == model_reply
    assert "这样处理的原因是" not in repository.turns[-1]["content"]
    assert "如果你想调整" not in repository.turns[-1]["content"]
    assert agent_calls[0]["user_question"] == "为什么这样改？"
    assert agent_calls[0]["proposed_content"] == "• 负责 FastAPI 接口开发"


def _follow_up_repository():
    block = {
        "id": "block-1",
        "kind": "bullet",
        "sectionId": "project_experience",
        "sectionName": "Project",
        "itemLabel": "item 1",
        "text": "Developed FastAPI API",
        "textHash": "hash-1",
        "locationLabel": "Project > item 1",
        "locatorConfidence": "high",
        "locator": {"sourceFormat": "txt"},
    }
    repository = _Repository([block])
    repository.suggestions.append({
        "id": "sug-1",
        "status": "proposed",
        "target": {"blockId": "block-1", "locationLabel": "Project > item 1"},
        "originalText": block["text"],
        "proposedText": "• Developed FastAPI API",
    })
    repository.turns.extend([
        {"id": "turn-suggestion", "role": "assistant", "content": "Suggestion", "messageKind": "suggestion", "payload": {"suggestionId": "sug-1"}},
        {"id": "turn-question", "role": "user", "content": "Why?", "messageKind": "text", "payload": {}},
    ])
    return repository


def test_graph_reports_missing_model_instead_of_emitting_a_template_explanation():
    repository = _follow_up_repository()

    result = ResumeAdvisorGraph(repository).run(
        user_id="u1",
        session_id="session-1",
        run_id="run-follow-up-no-model",
    )

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unavailable"
    assert repository.turns[-1]["payload"]["errorCode"] == "resume_advisor_suggestion_follow_up_unavailable"
    assert repository.turns[-1]["content"] == ""
    assert len(repository.suggestions) == 1


def test_graph_reports_model_failure_without_persisting_a_fallback_explanation(monkeypatch):
    repository = _follow_up_repository()

    async def failed_explain(_self, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "backend.agents.resume_copywriter.ResumeCopywriter.explain_advisor_suggestion",
        failed_explain,
    )

    result = ResumeAdvisorGraph(repository, model_client=object(), model_id="configured-model").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-follow-up-model-failure",
    )

    assert result["status"] == "WAITING_FOR_USER"
    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["payload"]["modelStatus"] == "failed"
    assert repository.turns[-1]["payload"]["errorCode"] == "resume_advisor_suggestion_follow_up_failed"
    assert repository.turns[-1]["content"] == ""
    assert repository.events[-1]["event_type"] == "model_failure"


def test_graph_does_not_persist_unverified_model_claims_in_follow_up_explanations(monkeypatch):
    repository = _follow_up_repository()

    async def unsafe_explain(_self, **_kwargs):
        return "原文未写明 Redis，但可以强调 Redis 缓存。"

    monkeypatch.setattr(
        "backend.agents.resume_copywriter.ResumeCopywriter.explain_advisor_suggestion",
        unsafe_explain,
    )

    ResumeAdvisorGraph(repository, model_client=object(), model_id="configured-model").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-follow-up-unsafe-output",
    )

    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unsafe_output"
    assert repository.turns[-1]["content"] == ""


def test_graph_does_not_persist_unverified_chinese_responsibilities_in_follow_up_explanations(monkeypatch):
    repository = _follow_up_repository()

    async def unsafe_explain(_self, **_kwargs):
        return "这说明候选人能够独立完成跨部门需求协调。"

    monkeypatch.setattr(
        "backend.agents.resume_copywriter.ResumeCopywriter.explain_advisor_suggestion",
        unsafe_explain,
    )

    ResumeAdvisorGraph(repository, model_client=object(), model_id="configured-model").run(
        user_id="u1",
        session_id="session-1",
        run_id="run-follow-up-unsafe-responsibility",
    )

    assert repository.turns[-1]["message_kind"] == "error"
    assert repository.turns[-1]["payload"]["modelStatus"] == "unsafe_output"
    assert repository.turns[-1]["content"] == ""


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

    _configured_graph(repository).run(user_id="u1", session_id="session-1", run_id="run-free-form-revision")

    assert repository.suggestions[0]["status"] == "needs_revision"
    assert repository.suggestions[-1]["parentSuggestionId"] == "sug-1"
    assert repository.suggestions[-1]["target"]["blockId"] == "block-1"


def test_graph_persists_a_model_generated_shorten_request_as_a_new_version(monkeypatch):
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

    graph = _configured_graph(repository)
    monkeypatch.setattr(
        graph,
        "_draft_suggestion",
        lambda *_args, **_kwargs: SuggestionDraft(
            proposed_text="• 负责 FastAPI 接口开发",
            issue="根据用户反馈压缩已有事实。",
            rationale="由配置模型生成。",
            expected_impact="更简洁地呈现已有职责。",
            priority="high",
        ),
    )

    graph.run(user_id="u1", session_id="session-1", run_id="run-shorten")

    assert repository.suggestions[-1]["proposedText"] == "• 负责 FastAPI 接口开发"


def test_graph_completes_after_an_applied_suggestion_without_a_keyword_question():
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

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.turns[-1]["message_kind"] == "completion"


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

    result = LangGraphResumeAdvisor(
        repository,
        checkpointer=InMemorySaver(),
        model_provider=_configured_model_provider,
    ).run(user_id="u1", session_id="session-1", run_id="run-langgraph")

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
    graph = LangGraphResumeAdvisor(
        repository,
        checkpointer=InMemorySaver(),
        model_provider=_configured_model_provider,
    )
    graph.run(user_id="u1", session_id="session-1", run_id="run-langgraph")
    repository.suggestions[0]["status"] = "applied"

    result = graph.resume(user_id="u1", session_id="session-1", payload={"messageId": "turn-2"})

    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert repository.turns[-1]["message_kind"] == "completion"
