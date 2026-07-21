from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class FactIssue(BaseModel):
    category: str
    claim: str
    message: str


class FactVerificationResult(BaseModel):
    is_supported: bool
    status: str
    fact_issues: list[FactIssue] = Field(default_factory=list)


class QualityReviewResult(BaseModel):
    is_passed: bool
    status: str
    issues: list[str] = Field(default_factory=list)


def verify_suggestion_facts(*, original_text: str, proposed_text: str, resume_evidence_texts: list[str] | None = None, confirmed_facts: list[dict[str, Any]] | None = None, jd_text: str = "") -> FactVerificationResult:
    evidence = " ".join([original_text, *(resume_evidence_texts or []), *[str(item.get("claimValue") or "") for item in confirmed_facts or []]])
    issues = [FactIssue(category="quantitative", claim=number, message=f"新增数字缺少简历或项目证据：{number}") for number in re.findall(r"\d+(?:\.\d+)?%?", proposed_text) if number not in evidence]
    return FactVerificationResult(is_supported=not issues, status="supported" if not issues else "unsupported", fact_issues=issues)


def review_suggestion_quality(*, original_text: str, proposed_text: str, evidence_block_ids: list[str] | None = None, fact_status: str = "supported") -> QualityReviewResult:
    issues = []
    if not proposed_text.strip(): issues.append("修改内容不能为空")
    if not (evidence_block_ids or []): issues.append("修改必须关联简历证据")
    if fact_status != "supported": issues.append("事实校验未通过")
    return QualityReviewResult(is_passed=not issues, status="passed" if not issues else "failed", issues=issues)
