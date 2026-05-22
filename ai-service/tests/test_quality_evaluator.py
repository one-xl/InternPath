from app.evaluation.quality_evaluator import evaluate_report_quality
from app.evaluation.regression_cases import REGRESSION_CASES


def evaluate_case(name):
    case = next(item for item in REGRESSION_CASES if item["name"] == name)
    return evaluate_report_quality(
        final_report=case["finalReport"],
        evidence_summary=case["evidenceSummary"],
        hallucination_control=case["hallucinationControl"],
        citations=case["citations"],
        verification_results=case["verificationResults"],
        workflow_logs=[],
    )


def issue_types(result):
    return {item["type"] for item in result["issues"]}


def test_normal_regression_case_is_usable_quality():
    result = evaluate_case("normal_spring_boot_supported")
    assert result["qualityGrade"] in {"A", "B"}
    assert result["qualityGateStatus"] == "PASSED"


def test_high_hallucination_risk_fails_gate():
    result = evaluate_case("langgraph_hallucination")
    assert result["qualityGateStatus"] == "FAILED"
    assert "HIGH_HALLUCINATION_RISK" in issue_types(result)


def test_missing_citations_lower_citation_score():
    result = evaluate_case("missing_citations")
    assert result["scores"]["citationCompletenessScore"] <= 30
    assert "MISSING_CITATION" in issue_types(result)


def test_score_too_high_is_flagged():
    result = evaluate_case("score_too_high")
    assert "SCORE_TOO_HIGH" in issue_types(result)
    assert result["qualityGateStatus"] in {"WARNING", "FAILED"}


def test_resume_fabrication_risk_is_flagged():
    result = evaluate_case("resume_fabrication_risk")
    assert "OVERSTATED_RESUME" in issue_types(result)
    assert result["scores"]["resumeHonestyScore"] < 70
