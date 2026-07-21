from __future__ import annotations

import re
from typing import Any

from app.evaluation.quality_evaluator import evaluate_report_quality
from app.rag.bm25_retriever import search_chunks_bm25
from app.rag.chunker import chunk_text
from app.verification.evidence_checker import extract_keywords, split_claims
from app.workflow.engine import WorkflowEngine
from app.workflow.state import WorkflowState

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
WEAK_THRESHOLD = 0.25


class BaseNode:
    node_name = "BaseNode"
    critical = True

    def input_summary(self, state: WorkflowState) -> str:
        return ""

    def output_summary(self, state: WorkflowState) -> str:
        return ""


class JDParserNode(BaseNode):
    node_name = "JDParserNode"

    def input_summary(self, state: WorkflowState) -> str:
        return f"JD length: {len(state.request.jdText)} chars"

    def run(self, state: WorkflowState) -> WorkflowState:
        jd_text = state.request.jdText
        keywords = extract_keywords_for_report(jd_text)
        state.data["jdParse"] = {
            "jobTitle": "",
            "company": "",
            "responsibilities": split_to_items(jd_text, ["负责", "职责", "工作"]),
            "requirements": keywords,
            "bonus": split_to_items(jd_text, ["优先", "加分"]),
            "techKeywords": keywords,
            "rawSummary": jd_text[:240],
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        parsed = state.data.get("jdParse", {})
        return f"Parsed {len(parsed.get('techKeywords', []))} tech keywords, {len(parsed.get('requirements', []))} requirements"


class ResumeContextNode(BaseNode):
    node_name = "ResumeContextNode"

    def input_summary(self, state: WorkflowState) -> str:
        return (
            f"resume length: {len(state.request.resumeText)} chars, "
            f"knowledge texts: {len(state.request.knowledgeTexts)}, documents: {len(state.request.documents)}"
        )

    def run(self, state: WorkflowState) -> WorkflowState:
        documents: list[Any] = []
        all_documents: list[Any] = [
            {"documentId": "JD", "content": state.request.jdText, "metadata": {"sourceType": "JD"}}
        ]
        if state.request.resumeText.strip():
            all_documents.append(
                {"documentId": "RESUME", "content": state.request.resumeText, "metadata": {"sourceType": "RESUME"}}
            )
        if state.request.documents:
            for document in state.request.documents:
                raw = document.model_dump() if hasattr(document, "model_dump") else dict(document)
                if str(raw.get("documentId") or "").strip() and str(raw.get("content") or "").strip():
                    documents.append(raw)
        else:
            for index, text in enumerate(state.request.knowledgeTexts):
                if text.strip():
                    documents.append(
                        {
                            "documentId": f"KNOWLEDGE_{index + 1}",
                            "content": text,
                            "metadata": {"sourceType": "KNOWLEDGE_BASE"},
                        }
                    )
        all_documents.extend(documents)
        context_documents = build_chunks(documents)
        all_chunks = build_chunks(all_documents)
        state.data["resumeContext"] = {
            "resumeSummary": state.request.resumeText[:240],
            "documentCount": len(documents),
            "chunkCount": len(context_documents),
            "contextTexts": list(state.request.knowledgeTexts),
            "contextDocuments": context_documents,
            "allChunks": all_chunks,
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        ctx = state.data.get("resumeContext", {})
        return f"context documents: {ctx.get('documentCount', 0)}, chunks: {ctx.get('chunkCount', 0)}"


class RAGRetrieverNode(BaseNode):
    node_name = "RAGRetrieverNode"

    def input_summary(self, state: WorkflowState) -> str:
        keywords = state.data.get("jdParse", {}).get("techKeywords", [])
        return f"query: {', '.join(keywords[:6])}; enableRag={state.request.options.enableRag}"

    def run(self, state: WorkflowState) -> WorkflowState:
        ctx = state.data.get("resumeContext", {})
        evidence_chunks = ctx.get("contextDocuments") or ctx.get("allChunks") or []
        if state.request.options.enableRag:
            existing = state.data.get("retrieval", {}).get("retrievedChunks")
            if existing:
                retrieved = existing
            else:
                query = " ".join(state.data.get("jdParse", {}).get("techKeywords", [])) or state.request.jdText[:500]
                retrieved = search_chunks_bm25(evidence_chunks, query, 8)
        else:
            retrieved = []
        state.data["retrieval"] = {
            "retrievedChunks": retrieved,
            "citationsDraft": build_citations_from_chunks(retrieved),
            "evidenceCount": len(retrieved),
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"retrieved chunks: {state.data.get('retrieval', {}).get('evidenceCount', 0)}"


class DraftReportNode(BaseNode):
    node_name = "DraftReportNode"

    def input_summary(self, state: WorkflowState) -> str:
        return "JD parse + resume context + retrieved chunks"

    def run(self, state: WorkflowState) -> WorkflowState:
        draft = build_draft_report(
            state.request.jdText,
            state.request.resumeText,
            state.data.get("jdParse", {}),
        )
        state.data["draftReport"] = draft
        return state

    def output_summary(self, state: WorkflowState) -> str:
        score = state.data.get("draftReport", {}).get("matchScore", {}).get("overall")
        return f"draft match score: {score}"


class ClaimExtractionNode(BaseNode):
    node_name = "ClaimExtractionNode"

    def input_summary(self, state: WorkflowState) -> str:
        return "draftReport fields"

    def run(self, state: WorkflowState) -> WorkflowState:
        report_text = report_to_text(state.data.get("draftReport", {}))
        claims = []
        for index, text in enumerate(split_claims(report_text), start=1):
            claims.append(
                {
                    "claimId": f"claim-{index}",
                    "claimText": text,
                    "claimType": classify_claim(text),
                    "sourceNeeded": source_needed_for_claim(text),
                }
            )
        state.data["claims"] = claims
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"claims extracted: {len(state.data.get('claims', []))}"


class EvidenceCheckNode(BaseNode):
    node_name = "EvidenceCheckNode"

    def input_summary(self, state: WorkflowState) -> str:
        return f"claims: {len(state.data.get('claims', []))}"

    def run(self, state: WorkflowState) -> WorkflowState:
        from app.verification.evidence_checker import verify_claims_section_aware
        chunks = state.data.get("retrieval", {}).get("retrievedChunks") or state.data.get("resumeContext", {}).get("allChunks", [])

        claims = state.data.get("claims", [])
        claims_texts = [claim["claimText"] for claim in claims]
        verification_results = verify_claims_section_aware(claims_texts, chunks)

        results = []
        supported = weak = unsupported = contradicted = 0

        for claim, v_res in zip(claims, verification_results):
            status = v_res["status"]
            confidence = v_res["confidenceScore"]

            if status == "supported":
                supported += 1
            elif status == "weak":
                weak += 1
            else:
                unsupported += 1

            ev_chunks = []
            if v_res.get("evidence"):
                matching_chunk_id = v_res["evidence"]["chunkId"]
                matching_chunk = next((c for c in chunks if c.get("chunkId") == matching_chunk_id), None)
                if matching_chunk:
                    ev_chunks.append({
                        "documentId": matching_chunk["documentId"],
                        "chunkId": matching_chunk["chunkId"],
                        "sourceType": matching_chunk.get("sourceType") or matching_chunk.get("metadata", {}).get("sourceType", "KNOWLEDGE_BASE"),
                        "fileName": matching_chunk.get("fileName") or matching_chunk.get("metadata", {}).get("fileName", ""),
                        "text": matching_chunk.get("text", "")[:500],
                        "sectionType": matching_chunk.get("sectionType") or matching_chunk.get("metadata", {}).get("sectionType", "generic_section"),
                        "sectionTitle": matching_chunk.get("sectionTitle") or matching_chunk.get("metadata", {}).get("sectionTitle", "Document Content"),
                        "hierarchy": matching_chunk.get("hierarchy") or matching_chunk.get("metadata", {}).get("hierarchy") or ["Document Content"],
                        "importance": float(matching_chunk.get("importance") or matching_chunk.get("metadata", {}).get("importance", 0.60)),
                        "keywords": matching_chunk.get("keywords") or matching_chunk.get("metadata", {}).get("keywords", []),
                        "metadata": matching_chunk.get("metadata", {})
                    })
            if not ev_chunks and chunks:
                ev_chunks = claim_evidence_chunks(chunks, confidence)

            results.append(
                {
                    "claimId": claim["claimId"],
                    "claimText": claim["claimText"],
                    "claimType": claim["claimType"],
                    "status": status,
                    "confidenceScore": round(confidence, 3),
                    "reason": build_verification_reason(status, v_res["matched_keywords"]),
                    "evidenceChunks": ev_chunks,
                    "matchedKeywords": v_res["matched_keywords"],
                    "evidence": v_res.get("evidence")
                }
            )

        total = supported + weak + unsupported + contradicted
        state.data["verification"] = {
            "verificationResults": results,
            "evidenceSummary": {
                "totalClaims": total,
                "supportedClaims": supported,
                "weakClaims": weak,
                "unsupportedClaims": unsupported,
                "contradictedClaims": contradicted,
                "evidenceCoverage": round(supported / total, 3) if total else 0,
            },
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        summary = state.data.get("verification", {}).get("evidenceSummary", {})
        return f"supported: {summary.get('supportedClaims', 0)}, weak: {summary.get('weakClaims', 0)}, unsupported: {summary.get('unsupportedClaims', 0)}"


class HallucinationDetectNode(BaseNode):
    node_name = "HallucinationDetectNode"

    def input_summary(self, state: WorkflowState) -> str:
        return "verificationResults"

    def run(self, state: WorkflowState) -> WorkflowState:
        results = state.data.get("verification", {}).get("verificationResults", [])
        risk = risk_level(
            sum(1 for item in results if item["status"] == "unsupported"),
            sum(1 for item in results if item["status"] == "weak"),
            len(results),
        )
        if not state.request.options.enableHallucinationCheck:
            control = {"riskLevel": "NOT_CHECKED", "detectedItems": [], "rewrittenItems": []}
        else:
            control = {
                "riskLevel": risk,
                "detectedItems": [item for item in results if item["status"] in {"weak", "unsupported", "contradicted"}],
                "rewrittenItems": [],
            }
        state.data["hallucinationControl"] = control
        return state

    def output_summary(self, state: WorkflowState) -> str:
        control = state.data.get("hallucinationControl", {})
        return f"risk: {control.get('riskLevel')}, detected: {len(control.get('detectedItems', []))}"


class RewriteNode(BaseNode):
    node_name = "RewriteNode"
    critical = False

    def input_summary(self, state: WorkflowState) -> str:
        return f"enableRewrite={state.request.options.enableRewrite}"

    def run(self, state: WorkflowState) -> WorkflowState:
        draft = state.data.get("draftReport", {})
        results = state.data.get("verification", {}).get("verificationResults", [])
        if not state.request.options.enableRewrite:
            state.data["rewrittenReport"] = draft
            state.data["rewrittenItems"] = []
            return state
        unsupported = [item["claimText"] for item in results if item["status"] == "unsupported"]
        weak = [item["claimText"] for item in results if item["status"] == "weak"]
        rewritten = dict(draft)
        rewritten_items = [f"证据不足，不能作为事实输出：{claim}" for claim in unsupported[:10]]
        rewritten_items.extend(f"证据较弱，建议降级表述：{claim}" for claim in weak[:10])
        if rewritten_items:
            rewritten["lowSupportNotice"] = rewritten_items
        suggestions = rewritten.setdefault("resumeSuggestions", {})
        directly_usable = suggestions.setdefault("directlyUsable", [])
        for recommendation in state.data.get("projectRerank", {}).get("recommendations", []):
            suggestion = str(recommendation.get("resumeSuggestion") or "").strip()
            if suggestion and suggestion not in directly_usable:
                directly_usable.append(suggestion)
        suggestions.setdefault("needToBuildFirst", [])
        state.data["rewrittenReport"] = rewritten
        state.data["rewrittenItems"] = rewritten_items
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"rewritten items: {len(state.data.get('rewrittenItems', []))}"


class CitationNode(BaseNode):
    node_name = "CitationNode"

    def input_summary(self, state: WorkflowState) -> str:
        return "verificationResults + retrievedChunks"

    def run(self, state: WorkflowState) -> WorkflowState:
        citations = []
        idx = 1
        for result in state.data.get("verification", {}).get("verificationResults", []):
            if result["status"] == "unsupported":
                continue
            for chunk in result.get("evidenceChunks", [])[:1]:
                citations.append(
                    {
                        "citationId": f"cite-{idx}",
                        "claimId": result["claimId"],
                        "claimText": result["claimText"],
                        "documentId": chunk.get("documentId", ""),
                        "sectionId": chunk.get("sectionId") or chunk.get("metadata", {}).get("sectionId") or f"sec-{chunk.get('sourceType', chunk.get('metadata', {}).get('sourceType', 'other'))}-pre",
                        "sectionType": chunk.get("sectionType") or chunk.get("metadata", {}).get("sectionType") or "generic_section",
                        "sectionTitle": chunk.get("sectionTitle") or chunk.get("metadata", {}).get("sectionTitle") or "Document Content",
                        "hierarchy": chunk.get("hierarchy") or chunk.get("metadata", {}).get("hierarchy") or ["Document Content"],
                        "chunkId": chunk.get("chunkId", ""),
                        "fileName": chunk.get("fileName") or chunk.get("metadata", {}).get("fileName", ""),
                        "retrievalScore": result.get("confidenceScore", 0.90),
                        "retrievalReasons": chunk.get("retrievalReasons", ["bm25_match"]),
                        "evidenceText": chunk.get("text", "")[:300],
                        # Maintain legacy fields for compatibility
                        "sourceType": chunk.get("sourceType") or chunk.get("metadata", {}).get("sourceType", ""),
                    }
                )
                idx += 1
        if not citations:
            fallback_chunks = (
                state.data.get("retrieval", {}).get("retrievedChunks")
                or state.data.get("resumeContext", {}).get("contextDocuments")
                or []
            )
            for chunk in fallback_chunks[:3]:
                metadata = chunk.get("metadata", {})
                citations.append(
                    {
                        "citationId": f"cite-{idx}",
                        "claimId": "",
                        "claimText": "",
                        "documentId": chunk.get("documentId", ""),
                        "sectionId": chunk.get("sectionId") or metadata.get("sectionId") or f"sec-{metadata.get('sourceType', 'other')}-pre",
                        "sectionType": chunk.get("sectionType") or metadata.get("sectionType") or "generic_section",
                        "sectionTitle": chunk.get("sectionTitle") or metadata.get("sectionTitle") or "Document Content",
                        "hierarchy": chunk.get("hierarchy") or metadata.get("hierarchy") or ["Document Content"],
                        "chunkId": chunk.get("chunkId", ""),
                        "fileName": chunk.get("fileName") or metadata.get("fileName", ""),
                        "retrievalScore": chunk.get("score"),
                        "retrievalReasons": chunk.get("retrievalReasons", ["retrieved_context"]),
                        "evidenceText": chunk.get("text", "")[:300],
                        "sourceType": chunk.get("sourceType") or metadata.get("sourceType", ""),
                    }
                )
                idx += 1
        state.data["citations"] = citations
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"citations: {len(state.data.get('citations', []))}"


class FinalReportNode(BaseNode):
    node_name = "FinalReportNode"

    def input_summary(self, state: WorkflowState) -> str:
        return "rewrittenReport + evidenceSummary + citations"

    def run(self, state: WorkflowState) -> WorkflowState:
        final_report = dict(state.data.get("rewrittenReport") or state.data.get("draftReport") or {})
        evidence_summary = state.data.get("verification", {}).get("evidenceSummary", empty_evidence_summary())
        hallucination_control = dict(state.data.get("hallucinationControl", {}))
        hallucination_control["rewrittenItems"] = state.data.get("rewrittenItems", [])
        citations = state.data.get("citations", [])
        final_report["evidenceSummary"] = evidence_summary
        final_report["hallucinationControl"] = hallucination_control
        final_report["citations"] = citations
        final_report["projectRecommendations"] = list(
            state.data.get("projectRerank", {}).get("recommendations", [])
        )
        state.data["finalReport"] = final_report
        return state

    def output_summary(self, state: WorkflowState) -> str:
        final_report = state.data.get("finalReport", {})
        return f"final report keys: {len(final_report)}"


class QualityEvaluationNode(BaseNode):
    node_name = "QualityEvaluationNode"

    def input_summary(self, state: WorkflowState) -> str:
        verification = state.data.get("verification", {})
        return (
            f"claims: {len(verification.get('verificationResults', []))}, "
            f"citations: {len(state.data.get('citations', []))}"
        )

    def run(self, state: WorkflowState) -> WorkflowState:
        state.data["qualityEvaluation"] = evaluate_report_quality(
            final_report=state.data.get("finalReport", {}),
            evidence_summary=state.data.get("verification", {}).get("evidenceSummary", empty_evidence_summary()),
            hallucination_control=state.data.get("hallucinationControl", {}),
            citations=state.data.get("citations", []),
            verification_results=state.data.get("verification", {}).get("verificationResults", []),
            workflow_logs=state.workflow_logs,
        )
        return state

    def output_summary(self, state: WorkflowState) -> str:
        quality = state.data.get("qualityEvaluation", {})
        return f"quality: {quality.get('finalQualityScore', 0)}, gate: {quality.get('qualityGateStatus', '-')}"


class SectionParserNode(BaseNode):
    node_name = "SectionParserNode"

    def input_summary(self, state: WorkflowState) -> str:
        return f"JD text: {len(state.request.jdText)} chars; Resume text: {len(state.request.resumeText)} chars"

    def run(self, state: WorkflowState) -> WorkflowState:
        from app.rag.section_parser import parse_sections
        jd_sections = parse_sections(state.request.jdText, source_type="jd")
        resume_sections = parse_sections(state.request.resumeText, source_type="resume")

        state.data["jdSections"] = jd_sections
        state.data["resumeSections"] = resume_sections
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"Parsed {len(state.data.get('jdSections', []))} JD sections and {len(state.data.get('resumeSections', []))} resume sections."


class MetadataChunkNode(BaseNode):
    node_name = "MetadataChunkNode"

    def input_summary(self, state: WorkflowState) -> str:
        ctx = state.data.get("resumeContext", {})
        return f"documents count: {ctx.get('documentCount', 0)}"

    def run(self, state: WorkflowState) -> WorkflowState:
        # Note: metadata inheritance is run seamlessly inside build_chunks
        return state

    def output_summary(self, state: WorkflowState) -> str:
        ctx = state.data.get("resumeContext", {})
        return f"Chunks generated: {ctx.get('chunkCount', 0)} chunks inherited section metadata."


class EmbeddingFormatNode(BaseNode):
    node_name = "EmbeddingFormatNode"

    def input_summary(self, state: WorkflowState) -> str:
        ctx = state.data.get("resumeContext", {})
        return f"chunks: {ctx.get('chunkCount', 0)}"

    def run(self, state: WorkflowState) -> WorkflowState:
        # Structured embedding is pre-generated in build_chunks
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return "Structured embedding texts generated successfully."


class HybridRetrievalNode(BaseNode):
    node_name = "HybridRetrievalNode"

    def input_summary(self, state: WorkflowState) -> str:
        keywords = state.data.get("jdParse", {}).get("techKeywords", [])
        return f"query: {', '.join(keywords[:6])}; enableRag={state.request.options.enableRag}"

    def run(self, state: WorkflowState) -> WorkflowState:
        from app.rag.hybrid_retriever import retrieve_hybrid
        ctx = state.data.get("resumeContext", {})
        evidence_chunks = ctx.get("contextDocuments") or ctx.get("allChunks") or []

        emb_config = {
            "model_id": getattr(state.request, "embeddingModelId", None),
            "provider": getattr(state.request, "embeddingProvider", None),
            "api_key": getattr(state.request, "embeddingApiKey", None),
            "base_url": getattr(state.request, "embeddingBaseUrl", None),
        }

        if state.request.options.enableRag:
            query = build_project_query(
                state.request.jdText,
                state.request.resumeText,
                state.data.get("jdParse", {}).get("techKeywords", []),
            )
            hybrid_results = retrieve_hybrid(evidence_chunks, query, 15, embedding_config=emb_config)
        else:
            hybrid_results = []

        state.data["hybridRetrieval"] = {
            "hybridChunks": hybrid_results,
            "evidenceCount": len(hybrid_results)
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return f"Hybrid retrieved chunks: {state.data.get('hybridRetrieval', {}).get('evidenceCount', 0)}"


class SemanticRankingNode(BaseNode):
    node_name = "SemanticRankingNode"

    def input_summary(self, state: WorkflowState) -> str:
        hybrid = state.data.get("hybridRetrieval", {}).get("hybridChunks", [])
        return f"hybrid candidates count: {len(hybrid)}"

    def run(self, state: WorkflowState) -> WorkflowState:
        from app.rag.project_reranker import rerank_projects
        from app.rag.semantic_ranker import rerank_chunks
        hybrid_chunks = state.data.get("hybridRetrieval", {}).get("hybridChunks", [])
        query = build_project_query(
            state.request.jdText,
            state.request.resumeText,
            state.data.get("jdParse", {}).get("techKeywords", []),
        )

        ranked = rerank_chunks(hybrid_chunks, query, 8)
        state.data["projectRerank"] = rerank_projects(
            ranked,
            jd_text=state.request.jdText,
            resume_text=state.request.resumeText,
        )

        state.data["retrieval"] = {
            "retrievedChunks": ranked,
            "citationsDraft": build_citations_from_chunks(ranked),
            "evidenceCount": len(ranked)
        }
        return state

    def output_summary(self, state: WorkflowState) -> str:
        return (
            f"Ranked Top {state.data.get('retrieval', {}).get('evidenceCount', 0)} chunks; "
            f"projects: {len(state.data.get('projectRerank', {}).get('recommendations', []))}."
        )


def build_project_query(jd_text: str, resume_text: str, keywords: list[str]) -> str:
    """Use both the JD and the current resume to retrieve project evidence."""
    keyword_text = " ".join(str(keyword) for keyword in keywords if str(keyword).strip())
    return "\n".join(
        part
        for part in (
            f"JD: {jd_text[:1400]}",
            f"Current resume: {resume_text[:1200]}",
            f"Key requirements: {keyword_text}",
        )
        if part.strip()
    )


def build_analyze_jd_workflow() -> WorkflowEngine:
    return WorkflowEngine(
        [
            JDParserNode(),
            ResumeContextNode(),
            SectionParserNode(),
            MetadataChunkNode(),
            EmbeddingFormatNode(),
            HybridRetrievalNode(),
            SemanticRankingNode(),
            RAGRetrieverNode(),
            DraftReportNode(),
            ClaimExtractionNode(),
            EvidenceCheckNode(),
            HallucinationDetectNode(),
            RewriteNode(),
            CitationNode(),
            FinalReportNode(),
            QualityEvaluationNode(),
        ]
    )


def workflow_response(task_id: str, state: WorkflowState) -> dict[str, Any]:
    evidence_summary = state.data.get("verification", {}).get("evidenceSummary", empty_evidence_summary())
    hallucination_control = state.data.get("hallucinationControl", {"riskLevel": "LOW", "detectedItems": [], "rewrittenItems": []})
    final_report = state.data.get("finalReport", {})
    return {
        "taskId": task_id,
        "status": "success",
        "data": {
            "draftReport": state.data.get("draftReport", {}),
            "finalReport": final_report,
            "evidenceSummary": evidence_summary,
            "hallucinationControl": hallucination_control,
            "citations": state.data.get("citations", []),
            "claims": state.data.get("claims", []),
            "verificationResults": state.data.get("verification", {}).get("verificationResults", []),
            "workflowLogs": state.workflow_logs,
            "qualityEvaluation": state.data.get("qualityEvaluation", {}),
            "projectRerank": state.data.get(
                "projectRerank",
                {"recommendations": [], "rerankMode": "fallback", "fallbackReason": "未执行项目重排"},
            ),
        },
    }


def build_chunks(documents: list[Any]) -> list[dict[str, Any]]:
    from app.rag.chunker import chunk_document_with_sections
    out: list[dict[str, Any]] = []
    for doc in documents:
        raw = doc.model_dump() if hasattr(doc, "model_dump") else dict(doc)
        document_id = str(raw.get("documentId", "")).strip()
        content = str(raw.get("content", ""))
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        if not document_id:
            continue

        # If it's already a single chunk with a chunkId (pre-chunked legacy flow)
        if raw.get("chunkId") or raw.get("chunk_id"):
            chunk_id = str(raw.get("chunkId") or raw.get("chunk_id"))
            text = content or str(raw.get("text", ""))
            importance_value = raw.get("importance")
            if importance_value is None:
                importance_value = metadata.get("importance", 0.60)
            try:
                importance = float(importance_value)
            except (TypeError, ValueError):
                importance = 0.60

            # Map default metadata
            out.append({
                "documentId": document_id,
                "chunkId": chunk_id,
                "text": text,
                "score": raw.get("score"),
                "sectionId": raw.get("sectionId") or f"sec-{metadata.get('sourceType', 'other')}-pre",
                "sectionType": raw.get("sectionType") or metadata.get("sectionType") or "generic_section",
                "sectionTitle": raw.get("sectionTitle") or metadata.get("sectionTitle") or "Document Content",
                "hierarchy": raw.get("hierarchy") or metadata.get("hierarchy") or ["Document Content"],
                "semanticType": raw.get("semanticType") or metadata.get("semanticType") or "general",
                "importance": importance,
                "keywords": raw.get("keywords") or metadata.get("keywords") or [],
                "embeddingText": raw.get("embeddingText") or text,
                "embedding": raw.get("embedding") or metadata.get("embedding"),
                "fileName": raw.get("fileName") or metadata.get("fileName") or "",
                "sourceType": raw.get("sourceType") or metadata.get("sourceType") or "other",
                "metadata": {**metadata, "chunkIndex": metadata.get("chunkIndex", 0)},
            })
            continue

        if not content.strip():
            continue

        # Metadata-aware chunking
        source_type = str(metadata.get("sourceType", "generic")).lower()
        file_name = str(metadata.get("fileName", "document.txt"))

        doc_chunks = chunk_document_with_sections(
            content=content,
            document_id=document_id,
            file_name=file_name,
            source_type=source_type,
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP
        )

        for c in doc_chunks:
            out.append({
                "documentId": c["documentId"],
                "chunkId": c["chunkId"],
                "text": c["chunkText"],
                "score": c.get("score"),
                "sectionId": c.get("sectionId"),
                "sectionType": c.get("sectionType"),
                "sectionTitle": c.get("sectionTitle"),
                "hierarchy": c.get("hierarchy"),
                "semanticType": c.get("semanticType"),
                "importance": c.get("importance"),
                "keywords": c.get("keywords"),
                "embeddingText": c.get("embeddingText"),
                "metadata": c.get("metadata")
            })

    return out


def build_citations_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "claimId": "",
            "claimText": "",
            "sourceType": chunk["metadata"].get("sourceType", "KNOWLEDGE_BASE"),
            "documentId": chunk["documentId"],
            "chunkId": chunk["chunkId"],
            "fileName": chunk["metadata"].get("fileName", ""),
            "evidenceText": chunk["text"][:300],
        }
        for chunk in chunks
    ]


def report_to_text(report: Any) -> str:
    if isinstance(report, str):
        return report
    parts: list[str] = []
    collect_report_text(report, parts)
    return "\n".join(parts)


def collect_report_text(value: Any, parts: list[str]) -> None:
    if isinstance(value, str) and value.strip():
        parts.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            collect_report_text(item, parts)
    elif isinstance(value, dict):
        for item in value.values():
            collect_report_text(item, parts)


def build_draft_report(jd_text: str, resume_text: str, jd_parse: dict[str, Any]) -> dict[str, Any]:
    keywords = jd_parse.get("techKeywords") or extract_keywords_for_report(jd_text)
    resume_keywords = extract_keywords_for_report(resume_text)
    resume_keyset = {item.lower() for item in resume_keywords}
    matched = [kw for kw in keywords if kw.lower() in resume_keyset]
    missing = [kw for kw in keywords if kw not in matched]
    overall = int((len(matched) / len(keywords)) * 100) if keywords else 0
    return {
        "reportTitle": "InternPath JD 求职匹配分析报告",
        "jobSummary": {
            "jobTitle": jd_parse.get("jobTitle", ""),
            "company": jd_parse.get("company", ""),
            "responsibilities": jd_parse.get("responsibilities", []),
            "requirements": jd_parse.get("requirements", []),
            "bonus": jd_parse.get("bonus", []),
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
        "finalConclusion": "该报告为节点化工作流生成版本，建议结合证据覆盖率继续补充材料。",
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


def split_to_items(text: str, markers: list[str]) -> list[str]:
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    matched = [line for line in lines if any(marker in line for marker in markers)]
    return matched[:8]


def classify_claim(text: str) -> str:
    if any(word in text for word in ("要求", "职责", "岗位", "优先")):
        return "JD_REQUIREMENT"
    if any(word in text for word in ("简历", "经历", "项目", "具备", "找到")):
        return "RESUME_FACT"
    if "匹配" in text or "overall" in text:
        return "MATCH_SCORE"
    if any(word in text for word in ("建议", "补齐", "学习", "优化")):
        return "SUGGESTION"
    return "GENERAL"


def source_needed_for_claim(text: str) -> str:
    ctype = classify_claim(text)
    if ctype == "JD_REQUIREMENT":
        return "JD"
    if ctype == "RESUME_FACT":
        return "RESUME"
    if ctype == "SUGGESTION":
        return "ANY"
    return "ANY"


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


def risk_level(unsupported: int, weak: int, total: int) -> str:
    if total == 0:
        return "LOW"
    rate = (unsupported + weak * 0.5) / total
    if rate >= 0.45:
        return "HIGH"
    if rate >= 0.2:
        return "MEDIUM"
    return "LOW"


def empty_evidence_summary() -> dict[str, Any]:
    return {
        "totalClaims": 0,
        "supportedClaims": 0,
        "weakClaims": 0,
        "unsupportedClaims": 0,
        "contradictedClaims": 0,
        "evidenceCoverage": 0,
    }
