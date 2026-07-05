"""FastAPI entrypoint for InternPath RAG and hallucination-control service."""

from __future__ import annotations

import sys
import os

# Add parent directory of ai-service to sys.path so we can import app_log
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.schemas import AnalyzeJdRequest, RagSearchRequest, VerifyReportRequest
from app.rag.bm25_retriever import search_chunks_bm25
from app.rag.chunker import chunk_text
from app.verification.evidence_checker import check_answer_faithfulness, split_claims
from app.workflow.engine import WorkflowExecutionError
from app.workflow.nodes import build_analyze_jd_workflow, workflow_response
from app.workflow.state import WorkflowState

app = FastAPI(title="InternPath AI Service", version="0.1.0")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import traceback
    traceback.print_exc()
    try:
        from app_log import log_event
        log_event(
            service="AI-SERVICE",
            level="ERROR",
            event="validation_error",
            detail=f"URL: {request.url.path} | Errors: {exc.errors()}"
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": f"参数校验失败: {str(exc.errors())}",
            "error_type": "RequestValidationError",
            "errors": exc.errors()
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    try:
        from app_log import log_event
        level = "ERROR" if exc.status_code >= 500 else "WARNING"
        log_event(
            service="AI-SERVICE",
            level=level,
            event="http_exception",
            detail=f"URL: {request.url.path} | Status: {exc.status_code} | Detail: {exc.detail}"
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_type": "HTTPException"
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    error_type = exc.__class__.__name__
    error_detail = str(exc) or "No detail provided"
    tb_str = traceback.format_exc()
    try:
        from app_log import log_event
        log_event(
            service="AI-SERVICE",
            level="ERROR",
            event="unhandled_exception",
            detail=f"URL: {request.url.path} | [{error_type}] {error_detail} | Traceback: {tb_str}"
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": f"AI 服务内部错误: [{error_type}] {error_detail}",
            "error_type": error_type,
            "reason": error_detail
        }
    )

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
WEAK_THRESHOLD = 0.25


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "internpath-ai-service"}


@app.post("/ai/rag/search")
def rag_search(request: RagSearchRequest) -> dict[str, Any]:
    chunks = build_chunks(request.documents)
    results = search_chunks_bm25(chunks, request.query, request.topK)
    return {"query": request.query.strip(), "results": results}


@app.post("/ai/verify-report")
def verify_report(request: VerifyReportRequest) -> dict[str, Any]:
    report_text = report_to_text(request.report)
    evidence_chunks = normalize_evidence_chunks(request.evidenceChunks)
    if not evidence_chunks:
        source_docs = []
        if request.jdText.strip():
            source_docs.append({"documentId": "JD", "content": request.jdText, "metadata": {"sourceType": "JD"}})
        if request.resumeText.strip():
            source_docs.append(
                {"documentId": "RESUME", "content": request.resumeText, "metadata": {"sourceType": "RESUME"}}
            )
        evidence_chunks = build_chunks(source_docs)
    return verify_text_against_evidence(report_text, evidence_chunks, request.report)


@app.post("/ai/analyze-jd")
def analyze_jd(request: AnalyzeJdRequest) -> dict[str, Any]:
    state = WorkflowState(request=request)
    workflow = build_analyze_jd_workflow()
    try:
        from app_log import log_event
        log_event(
            service="AI-SERVICE",
            level="INFO",
            event="analyze_jd_start",
            detail=f"taskId={request.taskId} | userId={request.userId}"
        )
    except Exception:
        pass

    try:
        state = workflow.run(state)
    except WorkflowExecutionError as exc:
        try:
            from app_log import log_event
            log_event(
                service="AI-SERVICE",
                level="ERROR",
                event="analyze_jd_workflow_failed",
                detail=f"taskId={request.taskId} | userId={request.userId} | error={str(exc)}"
            )
        except Exception:
            pass
        return {
            "taskId": request.taskId,
            "status": "failed",
            "data": {
                "draftReport": state.data.get("draftReport", {}),
                "finalReport": state.data.get("finalReport", {}),
                "evidenceSummary": state.data.get("verification", {}).get("evidenceSummary", {}),
                "hallucinationControl": state.data.get("hallucinationControl", {}),
                "citations": state.data.get("citations", []),
                "claims": state.data.get("claims", []),
                "verificationResults": state.data.get("verification", {}).get("verificationResults", []),
                "workflowLogs": state.workflow_logs,
                "qualityEvaluation": state.data.get("qualityEvaluation", {}),
            },
        }

    try:
        from app_log import log_event
        log_event(
            service="AI-SERVICE",
            level="INFO",
            event="analyze_jd_success",
            detail=f"taskId={request.taskId} | userId={request.userId}"
        )
    except Exception:
        pass
    return workflow_response(request.taskId, state)


def build_chunks(documents: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents:
        raw = doc.model_dump() if hasattr(doc, "model_dump") else dict(doc)
        document_id = str(raw.get("documentId", "")).strip()
        content = str(raw.get("content", ""))
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        if not document_id or not content.strip():
            continue
        for idx, text in enumerate(chunk_text(content, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)):
            chunk_id = str(raw.get("chunkId") or f"{document_id}#chunk-{idx}")
            if raw.get("chunkId"):
                out.append(
                    {
                        "documentId": document_id,
                        "chunkId": chunk_id,
                        "text": content,
                        "metadata": {**metadata, "chunkIndex": metadata.get("chunkIndex", idx)},
                    }
                )
                break
            out.append(
                {
                    "documentId": document_id,
                    "chunkId": chunk_id,
                    "text": text,
                    "metadata": {**metadata, "chunkIndex": idx},
                }
            )
    return out


def normalize_evidence_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        text = str(chunk.get("text") or chunk.get("textPreview") or chunk.get("evidenceText") or "")
        if not text.strip():
            continue
        document_id = str(chunk.get("documentId") or chunk.get("document_id") or f"evidence-{idx + 1}")
        chunk_id = str(chunk.get("chunkId") or chunk.get("chunk_id") or f"{document_id}#chunk-{idx}")
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        out.append({"documentId": document_id, "chunkId": chunk_id, "text": text, "metadata": metadata})
    return out


def report_to_text(report: Any) -> str:
    if isinstance(report, str):
        return report
    if isinstance(report, dict):
        parts: list[str] = []
        collect_report_text(report, parts)
        return "\n".join(parts)
    return str(report)


def collect_report_text(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        if value.strip():
            parts.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            collect_report_text(item, parts)
    elif isinstance(value, dict):
        for item in value.values():
            collect_report_text(item, parts)


def verify_text_against_evidence(
    report_text: str,
    evidence_chunks: list[dict[str, Any]],
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    citations = evidence_chunks_to_citations(evidence_chunks)
    faithfulness = check_answer_faithfulness(report_text, citations)
    claims = faithfulness["claims"]
    verification_results = []
    supported = weak = unsupported = contradicted = 0
    for idx, claim in enumerate(claims, start=1):
        matched = claim.get("matched_keywords") or []
        keywords = claim.get("keywords") or []
        ratio = len(matched) / len(keywords) if keywords else 0.0
        evidence = claim_evidence_chunks(evidence_chunks, ratio)
        if claim.get("supported") is True:
            status = "supported"
            supported += 1
        elif ratio >= WEAK_THRESHOLD:
            status = "weak"
            weak += 1
        else:
            status = "unsupported"
            unsupported += 1
        verification_results.append(
            {
                "claimId": f"claim-{idx}",
                "claimText": claim.get("claim", ""),
                "claimType": "GENERAL",
                "status": status,
                "confidenceScore": round(ratio, 3),
                "reason": build_verification_reason(status, matched),
                "evidenceChunks": evidence,
                "matchedKeywords": matched,
            }
        )

    total = supported + weak + unsupported + contradicted
    evidence_coverage = supported / total if total else 0.0
    risk = risk_level(unsupported, weak, total)
    rewritten_report = rewrite_low_support_report(report or {}, verification_results)
    return {
        "claims": claims,
        "verificationResults": verification_results,
        "hallucinationRisk": risk,
        "rewrittenReport": rewritten_report,
        "evidenceSummary": {
            "totalClaims": total,
            "supportedClaims": supported,
            "weakClaims": weak,
            "unsupportedClaims": unsupported,
            "contradictedClaims": contradicted,
            "evidenceCoverage": round(evidence_coverage, 3),
        },
        "citations": build_output_citations(verification_results, evidence_chunks),
    }


def evidence_chunks_to_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": idx + 1,
            "document_id": chunk["documentId"],
            "original_filename": chunk["metadata"].get("sourceType", ""),
            "chunk_index": chunk["metadata"].get("chunkIndex", idx),
            "score": chunk.get("score"),
            "text_preview": chunk["text"],
        }
        for idx, chunk in enumerate(chunks)
    ]


def claim_evidence_chunks(chunks: list[dict[str, Any]], confidence: float) -> list[dict[str, Any]]:
    if not chunks or confidence <= 0:
        return []
    return [
        {
            "documentId": chunk["documentId"],
            "chunkId": chunk["chunkId"],
            "sourceType": chunk["metadata"].get("sourceType", "KNOWLEDGE_BASE"),
            "fileName": chunk["metadata"].get("fileName", ""),
            "text": chunk["text"][:500],
            "metadata": chunk.get("metadata", {}),
        }
        for chunk in chunks[:2]
    ]


def build_verification_reason(status: str, matched: list[str]) -> str:
    if status == "supported":
        return "claim 中的关键词可在证据片段中找到足够支持。"
    if status == "weak":
        return "claim 与证据存在部分关键词重合，但支持不足，建议谨慎表述。"
    if status == "contradicted":
        return "claim 与证据存在冲突。"
    return "未在证据片段中找到足够支持关键词。"


def build_output_citations(
    verification_results: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not chunks:
        return []
    citations = []
    for result in verification_results:
        if result["status"] == "unsupported":
            continue
        chunk = chunks[0]
        citations.append(
            {
                "claimId": result["claimId"],
                "sourceType": chunk["metadata"].get("sourceType", "KNOWLEDGE_BASE"),
                "fileName": chunk["metadata"].get("fileName", ""),
                "documentId": chunk["documentId"],
                "chunkId": chunk["chunkId"],
                "evidenceText": chunk["text"][:300],
            }
        )
    return citations


def risk_level(unsupported: int, weak: int, total: int) -> str:
    if total == 0:
        return "LOW"
    rate = (unsupported + weak * 0.5) / total
    if rate >= 0.45:
        return "HIGH"
    if rate >= 0.2:
        return "MEDIUM"
    return "LOW"


def build_draft_report(jd_text: str, resume_text: str) -> dict[str, Any]:
    keywords = extract_keywords_for_report(jd_text)
    resume_keywords = extract_keywords_for_report(resume_text)
    resume_keyset = {item.lower() for item in resume_keywords}
    matched = [kw for kw in keywords if kw.lower() in resume_keyset]
    missing = [kw for kw in keywords if kw not in matched]
    overall = int((len(matched) / len(keywords)) * 100) if keywords else 0
    return {
        "reportTitle": "InternPath JD 求职匹配分析报告",
        "jobSummary": {
            "jobTitle": "",
            "company": "",
            "responsibilities": [],
            "requirements": keywords,
            "bonus": [],
            "techKeywords": keywords,
        },
        "matchScore": {
            "overall": overall,
            "technical": overall,
            "project": 0,
            "education": 0,
            "experience": 0,
            "riskLevel": "LOW" if overall >= 60 else "MEDIUM",
        },
        "strengths": [f"简历中可找到与 {kw} 相关的表述" for kw in matched[:6]],
        "weaknesses": [f"简历中暂未找到 {kw} 的明确证据" for kw in missing[:6]],
        "resumeSuggestions": {
            "directlyUsable": [f"围绕 {kw} 补充已有经历中的量化结果" for kw in matched[:4]],
            "needToBuildFirst": [f"建议先补做或补充 {kw} 相关项目证据" for kw in missing[:4]],
        },
        "learningPath": [f"补齐 {kw} 的基础知识和项目练习" for kw in missing[:5]],
        "interviewQuestions": [f"请结合项目解释你如何使用 {kw}" for kw in keywords[:5]],
        "projectPackagingSuggestions": [],
        "evidenceSummary": empty_evidence_summary(),
        "hallucinationControl": {"riskLevel": "LOW", "detectedItems": [], "rewrittenItems": []},
        "citations": [],
        "finalConclusion": "该报告为第一阶段规则增强版本，建议结合证据覆盖率继续补充材料。",
    }


def extract_keywords_for_report(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}|[\u4e00-\u9fff]{2,}", text)
    stop = {"负责", "岗位", "要求", "相关", "能力", "工作", "经验", "熟悉", "优先", "进行", "使用"}
    out: list[str] = []
    for item in candidates:
        if item in stop or len(item) > 24:
            continue
        if item not in out:
            out.append(item)
    return out[:12]


def rewrite_low_support_report(report: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    unsupported = [item["claimText"] for item in results if item["status"] == "unsupported"]
    if not unsupported:
        return report
    rewritten = dict(report)
    rewritten["lowSupportNotice"] = [f"证据不足，不能直接断言：{claim}" for claim in unsupported[:10]]
    return rewritten


def build_final_report(
    draft_report: dict[str, Any],
    verification: dict[str, Any],
    enable_rewrite: bool,
) -> dict[str, Any]:
    final_report = verification["rewrittenReport"] if enable_rewrite else dict(draft_report)
    final_report.setdefault("reportTitle", "InternPath JD 求职匹配分析报告")
    final_report["evidenceSummary"] = verification["evidenceSummary"]
    final_report["hallucinationControl"] = {
        "riskLevel": verification["hallucinationRisk"],
        "detectedItems": [
            item for item in verification["verificationResults"] if item["status"] == "unsupported"
        ],
        "rewrittenItems": final_report.get("lowSupportNotice", []) if enable_rewrite else [],
    }
    final_report["citations"] = verification["citations"]
    return final_report


def empty_evidence_summary() -> dict[str, Any]:
    return {
        "totalClaims": 0,
        "supportedClaims": 0,
        "weakClaims": 0,
        "unsupportedClaims": 0,
        "contradictedClaims": 0,
        "evidenceCoverage": 0,
    }


def empty_verification(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "claims": split_claims(report_to_text(report)),
        "verificationResults": [],
        "hallucinationRisk": "NOT_CHECKED",
        "rewrittenReport": report,
        "evidenceSummary": empty_evidence_summary(),
        "citations": [],
    }
