from __future__ import annotations

from typing import Any


REGRESSION_CASES: list[dict[str, Any]] = [
    {
        "name": "normal_spring_boot_supported",
        "finalReport": {"matchScore": {"overall": 82}, "resumeSuggestions": {"directlyUsable": ["Spring Boot project metrics"], "needToBuildFirst": []}},
        "evidenceSummary": {"totalClaims": 4, "supportedClaims": 3, "weakClaims": 1, "unsupportedClaims": 0, "contradictedClaims": 0},
        "hallucinationControl": {"riskLevel": "LOW", "detectedItems": [], "rewrittenItems": []},
        "citations": [{"documentId": "resume", "chunkId": "resume-0", "evidenceText": "Spring Boot project"}],
        "verificationResults": [{"claimId": "c1", "claimType": "RESUME_FACT", "status": "supported"}],
        "expectedMinGrade": "B",
    },
    {
        "name": "langgraph_hallucination",
        "finalReport": {"matchScore": {"overall": 75}, "strengths": ["Candidate has LangGraph experience"]},
        "evidenceSummary": {"totalClaims": 3, "supportedClaims": 1, "weakClaims": 0, "unsupportedClaims": 2, "contradictedClaims": 0},
        "hallucinationControl": {"riskLevel": "HIGH", "detectedItems": [{"claimId": "c1"}], "rewrittenItems": []},
        "citations": [{"documentId": "resume", "chunkId": "resume-0", "evidenceText": "Python project"}],
        "verificationResults": [{"claimId": "c1", "claimType": "RESUME_FACT", "status": "unsupported"}],
        "expectedGate": "FAILED",
    },
    {
        "name": "missing_citations",
        "finalReport": {"matchScore": {"overall": 78}},
        "evidenceSummary": {"totalClaims": 5, "supportedClaims": 4, "weakClaims": 1, "unsupportedClaims": 0, "contradictedClaims": 0},
        "hallucinationControl": {"riskLevel": "LOW", "detectedItems": [], "rewrittenItems": []},
        "citations": [],
        "verificationResults": [{"claimId": f"c{i}", "claimType": "GENERAL", "status": "supported"} for i in range(5)],
        "expectedLowCitationScore": True,
    },
    {
        "name": "score_too_high",
        "finalReport": {"matchScore": {"overall": 92}, "weaknesses": ["Spring", "Redis", "Docker", "SQL"]},
        "evidenceSummary": {"totalClaims": 6, "supportedClaims": 1, "weakClaims": 2, "unsupportedClaims": 3, "contradictedClaims": 0},
        "hallucinationControl": {"riskLevel": "MEDIUM", "detectedItems": [{"claimId": "c2"}], "rewrittenItems": []},
        "citations": [{"documentId": "resume", "chunkId": "resume-0", "evidenceText": "Basic Java"}],
        "verificationResults": [{"claimId": "c1", "claimType": "MATCH_SCORE", "status": "unsupported"}],
        "expectedIssue": "SCORE_TOO_HIGH",
    },
    {
        "name": "resume_fabrication_risk",
        "finalReport": {"matchScore": {"overall": 70}, "resumeSuggestions": {"directlyUsable": ["直接写入未做过的 RAG 项目并包装成已完成"]}},
        "evidenceSummary": {"totalClaims": 3, "supportedClaims": 2, "weakClaims": 0, "unsupportedClaims": 1, "contradictedClaims": 0},
        "hallucinationControl": {"riskLevel": "MEDIUM", "detectedItems": [{"claimId": "c3"}], "rewrittenItems": []},
        "citations": [{"documentId": "resume", "chunkId": "resume-0", "evidenceText": "Course notes"}],
        "verificationResults": [{"claimId": "c3", "claimType": "RESUME_FACT", "status": "unsupported"}],
        "expectedIssue": "OVERSTATED_RESUME",
    },
]

