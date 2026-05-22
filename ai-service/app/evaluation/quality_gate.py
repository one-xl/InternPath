from __future__ import annotations

from typing import Any


def quality_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def quality_gate_status(
    *,
    final_quality_score: float,
    evidence_coverage_score: float,
    resume_honesty_score: float,
    hallucination_risk: str,
    total_claims: int,
    unsupported_claims: int,
    citations: list[dict[str, Any]],
    overall_match_score: float,
) -> str:
    unsupported_rate = unsupported_claims / total_claims if total_claims else 0.0
    if hallucination_risk == "HIGH":
        return "FAILED"
    if unsupported_rate > 0.4:
        return "FAILED"
    if total_claims > 3 and not citations:
        return "FAILED"
    if resume_honesty_score < 70:
        return "FAILED"
    if overall_match_score > 85 and evidence_coverage_score < 60:
        return "FAILED"
    if final_quality_score < 55:
        return "FAILED"
    if final_quality_score >= 70:
        return "PASSED"
    return "WARNING"
