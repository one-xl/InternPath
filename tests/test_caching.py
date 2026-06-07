import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.background_analyzer import (
    parse_job_description_py,
    check_hard_constraints_py,
    _JD_PARSE_CACHE,
    _HARD_CONSTRAINTS_CACHE
)
from backend.doubao_job_rag import (
    analyze_job_with_doubao,
    _DOUBAO_CACHE
)
from ai_analyzer import (
    AIAnalyzer,
    _SKILLS_CACHE,
    _DECISION_CACHE
)
from models import JobAnalysis, PersonalDecision


class MockResponse:
    def __init__(self, content):
        self.choices = [MagicMock()]
        self.choices[0].message.content = content
        self.usage = MagicMock()
        self.usage.prompt_tokens = 10
        self.usage.completion_tokens = 20
        self.usage.total_tokens = 30


def test_parse_job_description_caching():
    # Clear cache
    _JD_PARSE_CACHE.clear()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(json.dumps({
        "job_title": "Python Developer",
        "company": "Google",
        "requirements": [{"text": "Python skill", "priority": "must_have"}]
    }))

    jd_text = "Looking for a Python Developer at Google."
    model = "gpt-4"

    # First call: hits the LLM mock
    res1 = parse_job_description_py(mock_client, model, jd_text)
    assert res1["job_title"] == "Python Developer"
    assert mock_client.chat.completions.create.call_count == 1

    # Second call: should hit the cache and NOT call the mock completions client
    res2 = parse_job_description_py(mock_client, model, jd_text)
    assert res2["job_title"] == "Python Developer"
    assert mock_client.chat.completions.create.call_count == 1  # count remains 1

    # Third call: with different model, should call LLM again
    res3 = parse_job_description_py(mock_client, "gpt-3.5", jd_text)
    assert res3["job_title"] == "Python Developer"
    assert mock_client.chat.completions.create.call_count == 2


def test_check_hard_constraints_caching():
    _HARD_CONSTRAINTS_CACHE.clear()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(json.dumps({
        "hard_risks": [],
        "has_blocking_risk": False
    }))

    model = "gpt-4"
    parsed_jd = {"raw_text": "Must have Bachelor's degree.", "hard_constraints": [{"type": "degree"}]}
    parsed_resume = {"cleanedText": "Has a Bachelor's degree."}

    # First call
    res1 = check_hard_constraints_py(mock_client, model, parsed_jd, parsed_resume)
    assert res1["has_blocking_risk"] is False
    assert mock_client.chat.completions.create.call_count == 1

    # Second call (cache hit)
    res2 = check_hard_constraints_py(mock_client, model, parsed_jd, parsed_resume)
    assert res2["has_blocking_risk"] is False
    assert mock_client.chat.completions.create.call_count == 1

    # Call with different resume
    parsed_resume_diff = {"cleanedText": "Has a Master's degree."}
    res3 = check_hard_constraints_py(mock_client, model, parsed_jd, parsed_resume_diff)
    assert res3["has_blocking_risk"] is False
    assert mock_client.chat.completions.create.call_count == 2


def test_analyze_job_with_doubao_caching(monkeypatch):
    _DOUBAO_CACHE.clear()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(json.dumps({
        "decision": "yes",
        "matchScore": 80,
        "oneLineReason": "Fits well"
    }))

    # Mock AIAnalyzer._client in the context of doubao_job_rag
    mock_analyzer_instance = MagicMock()
    mock_analyzer_instance._client.return_value = (mock_client, "cfg-123", "openai", "gpt-4")

    # Use monkeypatch to patch AIAnalyzer instantiation in ai_analyzer
    monkeypatch.setattr("ai_analyzer.AIAnalyzer", lambda: mock_analyzer_instance)

    payload = {
        "jdText": "Python Dev",
        "targetType": "fulltime",
        "jobDirection": "backend",
        "draft": {},
        "resumeFile": {"cleanedText": "Senior Python dev"},
        "parsedResume": {"extractedProfile": {}}
    }

    # First call
    res1 = analyze_job_with_doubao(payload, user_id="user1")
    assert res1["decision"] == "yes"
    assert mock_client.chat.completions.create.call_count == 1

    # Second call (cache hit)
    res2 = analyze_job_with_doubao(payload, user_id="user1")
    assert res2["decision"] == "yes"
    assert mock_client.chat.completions.create.call_count == 1


def test_ai_analyzer_extract_skills_caching(monkeypatch):
    _SKILLS_CACHE.clear()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(json.dumps({
        "skills": ["Python"],
        "difficulty": "中等",
        "job_summary": "Python summary"
    }))

    analyzer = AIAnalyzer()
    monkeypatch.setattr(analyzer, "_client", lambda user_id: (mock_client, "cfg-123", "openai", "gpt-4"))

    # First call
    res1 = analyzer.extract_skills("Python JD", user_id="user1")
    assert "Python" in res1.skills
    assert mock_client.chat.completions.create.call_count == 1

    # Second call (cache hit)
    res2 = analyzer.extract_skills("Python JD", user_id="user1")
    assert "Python" in res2.skills
    assert mock_client.chat.completions.create.call_count == 1


def test_ai_analyzer_generate_personal_decision_caching(monkeypatch):
    _DECISION_CACHE.clear()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(json.dumps({
        "recommendation": "APPLY",
        "score_breakdown": {
            "hard_constraint_match": 90,
            "tech_stack_match": 85,
            "project_relevance": 80,
            "bonus_points": 75
        },
        "decision_reasons": ["Good fit"],
        "critical_gaps": [],
        "resume_rewrites": [],
        "evidence_needed": [],
        "action_plan": ["Apply"],
        "learning_plan": []
    }))

    analyzer = AIAnalyzer()
    monkeypatch.setattr(analyzer, "_client", lambda user_id: (mock_client, "cfg-123", "openai", "gpt-4"))

    analysis = JobAnalysis(skills=["Python"], difficulty="中等", job_summary="Python summary")

    # First call
    res1 = analyzer.generate_personal_decision(
        jd_text="Python JD",
        analysis=analysis,
        resume_text="My CV",
        user_id="user1"
    )
    assert res1.recommendation == "APPLY"
    assert mock_client.chat.completions.create.call_count == 1

    # Second call (cache hit)
    res2 = analyzer.generate_personal_decision(
        jd_text="Python JD",
        analysis=analysis,
        resume_text="My CV",
        user_id="user1"
    )
    assert res2.recommendation == "APPLY"
    assert mock_client.chat.completions.create.call_count == 1
