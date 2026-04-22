"""技能包 JSON 与 exam_options 序列化契约（与 AiSmartDrill 对齐）。"""

import json

import pytest
from pydantic import ValidationError

from models import ExamOptionsForPractice, SkillPackage
from practice_app import PracticeAppInvoker


def test_skill_package_json_keys_omit_none_without_exam_options():
    inv = PracticeAppInvoker()
    raw = inv.build_skill_package_json(
        ["Python", "SQL"],
        "direct",
        job_summary="后端实习",
        difficulty="中等",
    )
    data = json.loads(raw)
    assert "exam_options" not in data
    assert data["job_context"]["difficulty"] == "中等"
    assert data["version"] == "2.0"


def test_skill_package_json_includes_exam_options_snake_case():
    inv = PracticeAppInvoker()
    exam = ExamOptionsForPractice(
        domain_hint="Python",
        difficulty="中等",
        question_count=15,
    )
    raw = inv.build_skill_package_json(
        ["Python"],
        "ai_recommend",
        job_summary="",
        difficulty="简单",
        exam_options=exam,
    )
    data = json.loads(raw)
    eo = data["exam_options"]
    assert set(eo.keys()) == {"domain_hint", "difficulty", "question_count"}
    assert eo["domain_hint"] == "Python"
    assert eo["difficulty"] == "中等"
    assert eo["question_count"] == 15


def test_exam_options_partial_omits_none_fields():
    pkg = SkillPackage(
        skills=["Go"],
        practice_mode="direct",
        exam_options=ExamOptionsForPractice(question_count=5),
    )
    inv = PracticeAppInvoker()
    raw = inv.dumps_skill_package(pkg)
    data = json.loads(raw)
    assert data["exam_options"] == {"question_count": 5}


def test_dict_exam_options_coerced():
    inv = PracticeAppInvoker()
    raw = inv.build_skill_package_json(
        ["Rust"],
        "direct",
        exam_options={
            "domain_hint": "数据库",
            "question_count": 20,
        },
    )
    data = json.loads(raw)
    assert data["exam_options"]["domain_hint"] == "数据库"
    assert data["exam_options"]["question_count"] == 20
    assert "difficulty" not in data["exam_options"]


def test_question_count_bounds():
    with pytest.raises(ValidationError):
        ExamOptionsForPractice(question_count=0)
    with pytest.raises(ValidationError):
        ExamOptionsForPractice(question_count=51)
