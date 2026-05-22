from __future__ import annotations

from typing import Any

from app.evaluation.quality_gate import quality_gate_status, quality_grade


ISSUE_UNSUPPORTED = "UNSUPPORTED_CLAIM"
ISSUE_MISSING_CITATION = "MISSING_CITATION"
ISSUE_OVERSTATED_RESUME = "OVERSTATED_RESUME"
ISSUE_SCORE_TOO_HIGH = "SCORE_TOO_HIGH"
ISSUE_HIGH_HALLUCINATION = "HIGH_HALLUCINATION_RISK"


def evaluate_report_quality(
    *,
    final_report: dict[str, Any],
    evidence_summary: dict[str, Any],
    hallucination_control: dict[str, Any],
    citations: list[dict[str, Any]],
    verification_results: list[dict[str, Any]],
    workflow_logs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    evidence_score = score_evidence_coverage(evidence_summary, issues)
    hallucination_score = score_hallucination_risk(hallucination_control, issues)
    citation_score = score_citation_completeness(citations, verification_results, issues)
    honesty_score = score_resume_honesty(final_report, verification_results, issues)
    match_score = score_match_reasonableness(final_report, evidence_summary, evidence_score, verification_results, issues)

    final_quality_score = round(
        evidence_score * 0.30
        + hallucination_score * 0.25
        + citation_score * 0.20
        + honesty_score * 0.15
        + match_score * 0.10,
        1,
    )
    total_claims = int(evidence_summary.get("totalClaims") or len(verification_results) or 0)
    unsupported_claims = int(
        evidence_summary.get("unsupportedClaims")
        or sum(1 for item in verification_results if item.get("status") == "unsupported")
    )
    overall = extract_overall_match_score(final_report)
    gate = quality_gate_status(
        final_quality_score=final_quality_score,
        evidence_coverage_score=evidence_score,
        resume_honesty_score=honesty_score,
        hallucination_risk=str(hallucination_control.get("riskLevel") or "LOW"),
        total_claims=total_claims,
        unsupported_claims=unsupported_claims,
        citations=citations,
        overall_match_score=overall,
    )
    return {
        "finalQualityScore": final_quality_score,
        "qualityGrade": quality_grade(final_quality_score),
        "qualityGateStatus": gate,
        "scores": {
            "evidenceCoverageScore": evidence_score,
            "hallucinationRiskScore": hallucination_score,
            "citationCompletenessScore": citation_score,
            "resumeHonestyScore": honesty_score,
            "matchScoreReasonableness": match_score,
        },
        "issues": issues,
        "summary": build_summary(final_quality_score, gate, issues, workflow_logs or []),
    }


def score_evidence_coverage(evidence_summary: dict[str, Any], issues: list[dict[str, str]]) -> float:
    total = int(evidence_summary.get("totalClaims") or 0)
    if total <= 0:
        issues.append(issue(ISSUE_UNSUPPORTED, "MEDIUM", "No verifiable claims were extracted.", "Review the report structure and claim extraction prompt."))
        return 0.0
    supported = int(evidence_summary.get("supportedClaims") or 0)
    weak = int(evidence_summary.get("weakClaims") or 0)
    unsupported = int(evidence_summary.get("unsupportedClaims") or 0)
    score = (supported / total) * 100 - (unsupported / total) * 45 - (weak / total) * 20
    if unsupported:
        issues.append(issue(ISSUE_UNSUPPORTED, "HIGH" if unsupported / total > 0.4 else "MEDIUM", f"{unsupported} claims are unsupported.", "Rewrite unsupported claims as suggestions or remove them."))
    return clamp(score)


def score_hallucination_risk(hallucination_control: dict[str, Any], issues: list[dict[str, str]]) -> float:
    risk = str(hallucination_control.get("riskLevel") or "LOW")
    base = {"LOW": 90, "MEDIUM": 60, "HIGH": 30, "NOT_CHECKED": 50, "NOT_AVAILABLE": 40}.get(risk, 60)
    detected = hallucination_control.get("detectedItems") or []
    score = base - min(30, len(detected) * 5)
    if risk == "HIGH":
        issues.append(issue(ISSUE_HIGH_HALLUCINATION, "HIGH", "Hallucination risk is HIGH.", "Do not use this report before reviewing unsupported content."))
    elif risk == "MEDIUM" or detected:
        issues.append(issue(ISSUE_HIGH_HALLUCINATION, "MEDIUM", "Potential hallucination items were detected.", "Check low-confidence claims and evidence links."))
    return clamp(score)


def score_citation_completeness(
    citations: list[dict[str, Any]],
    verification_results: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> float:
    claim_count = len(verification_results)
    supported_like = [item for item in verification_results if item.get("status") in {"supported", "weak"}]
    if claim_count and not citations:
        issues.append(issue(ISSUE_MISSING_CITATION, "HIGH", "Report has claims but no citations.", "Return citations for supported and weak claims."))
        return 20.0
    if not claim_count:
        return 0.0
    malformed = 0
    for citation in citations:
        if not (citation.get("documentId") and citation.get("chunkId") and citation.get("evidenceText")):
            malformed += 1
    coverage = min(1.0, len(citations) / max(1, len(supported_like)))
    score = coverage * 100 - malformed * 12
    if malformed:
        issues.append(issue(ISSUE_MISSING_CITATION, "MEDIUM", f"{malformed} citations miss documentId, chunkId, or evidenceText.", "Preserve source metadata through RAG and citation formatting."))
    if coverage < 0.7:
        issues.append(issue(ISSUE_MISSING_CITATION, "MEDIUM", "Citation coverage is low for supported claims.", "Attach evidence citations to core claims."))
    return clamp(score)


def score_resume_honesty(
    final_report: dict[str, Any],
    verification_results: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> float:
    text = stringify(final_report).lower()
    risky_terms = [
        "directly write",
        "claim you have",
        "fabricate",
        "pretend",
        "包装成已完成",
        "直接写入未做过",
        "写成熟练掌握",
        "伪造",
        "编造",
    ]
    risky_hits = [term for term in risky_terms if term.lower() in text]
    unsupported_resume = [
        item for item in verification_results
        if item.get("status") in {"unsupported", "contradicted"} and item.get("claimType") == "RESUME_FACT"
    ]
    score = 100 - len(risky_hits) * 35 - len(unsupported_resume) * 20
    if risky_hits or unsupported_resume:
        issues.append(issue(ISSUE_OVERSTATED_RESUME, "HIGH", "Resume suggestions may overstate unsupported experience.", "Move unsupported content to needToBuildFirst and avoid fake experience."))
    return clamp(score)


def score_match_reasonableness(
    final_report: dict[str, Any],
    evidence_summary: dict[str, Any],
    evidence_score: float,
    verification_results: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> float:
    overall = extract_overall_match_score(final_report)
    weak_or_unsupported = sum(1 for item in verification_results if item.get("status") in {"weak", "unsupported", "contradicted"})
    total = int(evidence_summary.get("totalClaims") or len(verification_results) or 0)
    weaknesses = final_report.get("weaknesses") if isinstance(final_report.get("weaknesses"), list) else []
    score = 100.0
    if overall > 85 and evidence_score < 60:
        score = 35.0
        issues.append(issue(ISSUE_SCORE_TOO_HIGH, "HIGH", "Overall match score is high while evidence coverage is low.", "Lower the match score or add evidence for core skills."))
    elif total and overall > 85 and weak_or_unsupported / total > 0.35:
        score = 50.0
        issues.append(issue(ISSUE_SCORE_TOO_HIGH, "MEDIUM", "Overall match score may be too high for weak evidence.", "Calibrate match score using verification results."))
    elif overall > 85 and len(weaknesses) >= 4:
        score = 60.0
        issues.append(issue(ISSUE_SCORE_TOO_HIGH, "MEDIUM", "Many weaknesses are listed but overall score is above 85.", "Make the score consistent with missing core skills."))
    return clamp(score)


def extract_overall_match_score(final_report: dict[str, Any]) -> float:
    raw = (final_report.get("matchScore") or {}).get("overall") if isinstance(final_report, dict) else 0
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def build_summary(score: float, gate: str, issues: list[dict[str, str]], workflow_logs: list[dict[str, Any]]) -> str:
    failed_nodes = [item.get("nodeName") for item in workflow_logs if item.get("status") in {"FAILED", "WARNING"}]
    issue_text = f"{len(issues)} quality issues" if issues else "no major quality issues"
    workflow_text = f"; workflow warnings: {', '.join(filter(None, failed_nodes[:3]))}" if failed_nodes else ""
    return f"Quality score {score:.1f}, gate {gate}, {issue_text}{workflow_text}."


def issue(issue_type: str, severity: str, message: str, suggestion: str) -> dict[str, str]:
    return {"type": issue_type, "severity": severity, "message": message, "suggestion": suggestion}


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(stringify(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(stringify(item) for item in value.values())
    return str(value)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, float(value))), 1)
