"""Model-agnostic evaluation for externally generated answers and evidence."""

from __future__ import annotations

import re

from app.verification.evidence_checker import check_answer_faithfulness

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

_REFUSAL_PREFIXES = (
    "无法回答",
    "不能回答",
    "没有足够信息",
    "没有检索到足够信息",
    "知识库中没有",
    "暂时无法回答",
    "insufficient information",
    "not enough information",
    "there is not enough information",
    "there is insufficient information",
    "i cannot answer",
    "i can't answer",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "i am unable to answer",
)

_KNOWLEDGE_REFUSAL_PREFIXES = (
    "i do not know",
    "i don't know",
    "do not know",
    "don't know",
)


def is_refusal(answer: str) -> bool:
    """Return True when the answer clearly abstains instead of answering."""
    sentences = [part.strip().lower() for part in _SENTENCE_SPLIT_RE.split(answer)]
    for sentence in sentences:
        if not sentence:
            continue
        if any(sentence.startswith(marker) for marker in _REFUSAL_PREFIXES):
            return True
        for marker in _KNOWLEDGE_REFUSAL_PREFIXES:
            if sentence == marker:
                return True
            if sentence.startswith(f"{marker} because"):
                return True
    return False


def _optional_meta_str(raw: object, *, default: str = "unknown") -> str:
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


def _optional_run_id(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _validate_evidence(evidence: object, case_index: int) -> list[dict]:
    if evidence is None:
        return []
    if not isinstance(evidence, list):
        raise ValueError(f"case {case_index}: evidence must be a list")

    normalized: list[dict] = []
    for i, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise ValueError(f"case {case_index}: evidence {i} must be an object")
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError(f"case {case_index}: evidence {i} text must be a string")
        evidence_id = item.get("evidence_id", f"evidence-{i + 1}")
        source = item.get("source", "")
        normalized.append(
            {
                "evidence_id": str(evidence_id),
                "text": text,
                "source": str(source) if source is not None else "",
            }
        )
    return normalized


def _validate_external_case(case: dict, case_index: int) -> dict:
    if not isinstance(case, dict):
        raise ValueError(f"case {case_index}: must be an object")
    question = case.get("question")
    answer = case.get("answer")
    answerable = case.get("answerable")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"case {case_index}: question must be a non-empty string")
    if not isinstance(answer, str):
        raise ValueError(f"case {case_index}: answer must be a string")
    if not isinstance(answerable, bool):
        raise ValueError(f"case {case_index}: answerable must be a boolean")
    return {
        "case_id": str(case.get("case_id", f"case-{case_index + 1}")),
        "question": question.strip(),
        "answer": answer,
        "answerable": answerable,
        "evidence": _validate_evidence(case.get("evidence", []), case_index),
        "model": _optional_meta_str(case.get("model"), default="unknown"),
        "provider": _optional_meta_str(case.get("provider"), default="unknown"),
        "run_id": _optional_run_id(case.get("run_id")),
    }


def _evidence_to_citations(evidence: list[dict]) -> list[dict]:
    return [
        {
            "index": i + 1,
            "document_id": item["evidence_id"],
            "original_filename": item.get("source", ""),
            "chunk_index": i,
            "score": None,
            "text_preview": item["text"],
        }
        for i, item in enumerate(evidence)
    ]


def evaluate_external_answer_case(
    case: dict,
    *,
    min_support_rate: float | None = None,
    case_index: int = 0,
) -> dict:
    """Evaluate one externally generated answer against externally supplied evidence."""
    if min_support_rate is not None and not 0.0 <= min_support_rate <= 1.0:
        raise ValueError("min_support_rate must be between 0 and 1")

    normalized = _validate_external_case(case, case_index)
    citations = _evidence_to_citations(normalized["evidence"])
    faithfulness = check_answer_faithfulness(normalized["answer"], citations)
    refused = is_refusal(normalized["answer"])
    answerable = normalized["answerable"]
    refusal_correct = (not answerable and refused) if not answerable else None
    over_refusal = (answerable and refused) if answerable else None
    model = normalized["model"]
    provider = normalized["provider"]
    run_id = normalized["run_id"]

    reliable: bool | None
    if min_support_rate is None:
        reliable = None
    elif answerable:
        reliable = faithfulness["support_rate"] >= min_support_rate and not refused
    else:
        reliable = bool(refusal_correct)

    return {
        "case_id": normalized["case_id"],
        "question": normalized["question"],
        "model": model,
        "provider": provider,
        "run_id": run_id,
        "answerable": answerable,
        "evidence_count": len(citations),
        "refused": refused,
        "refusal_correct": refusal_correct,
        "over_refusal": over_refusal,
        "support_rate": faithfulness["support_rate"],
        "unsupported_claim_rate": faithfulness["unsupported_claim_rate"],
        "hallucination_proxy_rate": faithfulness["hallucination_proxy_rate"],
        "hallucination_rate": faithfulness["hallucination_rate"],
        "reliable": reliable,
        "faithfulness": faithfulness,
    }


def evaluate_external_answer_cases(
    cases: list[dict],
    *,
    min_support_rate: float | None = None,
) -> dict:
    """Evaluate external answer/evidence cases and return aggregate guardrail metrics."""
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    if min_support_rate is not None and not 0.0 <= min_support_rate <= 1.0:
        raise ValueError("min_support_rate must be between 0 and 1")

    rows = [
        evaluate_external_answer_case(
            case,
            min_support_rate=min_support_rate,
            case_index=i,
        )
        for i, case in enumerate(cases)
    ]

    answerable_rows = [row for row in rows if row["answerable"]]
    unanswerable_rows = [row for row in rows if not row["answerable"]]
    refusal_correct_count = sum(1 for row in unanswerable_rows if row["refusal_correct"])
    over_refusal_count = sum(1 for row in answerable_rows if row["over_refusal"])
    mean_support = (
        sum(float(row["support_rate"]) for row in rows) / len(rows) if rows else 0.0
    )
    mean_hallucination = (
        sum(float(row["hallucination_rate"]) for row in rows) / len(rows)
        if rows
        else 0.0
    )

    by_model_buckets: dict[str, list[dict]] = {}
    for row in rows:
        key = f'{row["provider"]}/{row["model"]}'
        by_model_buckets.setdefault(key, []).append(row)
    by_model = {
        key: _aggregate_rows_for_model_group(by_model_buckets[key])
        for key in sorted(by_model_buckets)
    }

    return {
        "min_support_rate": min_support_rate,
        "rows": rows,
        "aggregate": {
            "total": len(rows),
            "answerable_total": len(answerable_rows),
            "unanswerable_total": len(unanswerable_rows),
            "refusal_correct_count": refusal_correct_count,
            "refusal_accuracy": (
                refusal_correct_count / len(unanswerable_rows) if unanswerable_rows else 0.0
            ),
            "over_refusal_count": over_refusal_count,
            "over_refusal_rate": (
                over_refusal_count / len(answerable_rows) if answerable_rows else 0.0
            ),
            "mean_support_rate": mean_support,
            "mean_hallucination_rate": mean_hallucination,
            "by_model": by_model,
        },
    }


def _aggregate_rows_for_model_group(rows: list[dict]) -> dict:
    answerable_rows = [row for row in rows if row["answerable"]]
    unanswerable_rows = [row for row in rows if not row["answerable"]]
    refusal_correct_count = sum(1 for row in unanswerable_rows if row["refusal_correct"])
    over_refusal_count = sum(1 for row in answerable_rows if row["over_refusal"])
    mean_support = (
        sum(float(row["support_rate"]) for row in rows) / len(rows) if rows else 0.0
    )
    mean_hallucination = (
        sum(float(row["hallucination_rate"]) for row in rows) / len(rows)
        if rows
        else 0.0
    )
    return {
        "total": len(rows),
        "answerable_total": len(answerable_rows),
        "unanswerable_total": len(unanswerable_rows),
        "refusal_accuracy": (
            refusal_correct_count / len(unanswerable_rows) if unanswerable_rows else 0.0
        ),
        "over_refusal_rate": (
            over_refusal_count / len(answerable_rows) if answerable_rows else 0.0
        ),
        "mean_support_rate": mean_support,
        "mean_hallucination_rate": mean_hallucination,
    }
