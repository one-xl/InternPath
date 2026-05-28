"""Unit tests for the Structured RAG Upgrade components."""

import pytest
from app.rag.section_parser import parse_sections, classify_section_type
from app.rag.embedding_formatter import format_embedding_text
from app.rag.chunker import chunk_document_with_sections
from app.rag.hybrid_retriever import retrieve_hybrid, char_bigram_similarity
from app.rag.semantic_ranker import rerank_chunks, detect_query_semantic_type
from app.verification.evidence_checker import verify_claims_section_aware


def test_section_parser_resume():
    """Test resume parsing CN/EN section classification."""
    resume_text = """
    教育经历
    清华大学 计算机 本科
    
    项目经历
    InternPath 实习助手
    基于 FastAPI + SQLite 研发了 RAG 系统。
    
    专业技能
    Python, FastAPI, RAG, SQLite
    
    自我评价
    极其上进的技术实习生。
    """
    sections = parse_sections(resume_text, source_type="resume")
    assert len(sections) >= 4
    
    types = {s["sectionType"] for s in sections}
    assert "education" in types
    assert "project_experience" in types
    assert "skills" in types
    assert "self_introduction" in types


def test_section_parser_markdown_hierarchy():
    """Test markdown headings hierarchy list matching."""
    md_text = """
    # 我的简历
    ## 工作经历
    ### 腾讯科技
    我在此担任后端实习生。
    ### 阿里巴巴
    我在此做大数据研发。
    """
    sections = parse_sections(md_text, source_type="resume")
    assert len(sections) >= 2
    
    # Verify hierarchy
    tencent_sec = next(s for s in sections if "腾讯科技" in s["title"])
    assert tencent_sec["hierarchy"] == ["我的简历", "工作经历", "腾讯科技"]
    assert tencent_sec["level"] == 3


def test_section_parser_fallback():
    """Test fallback when no headers are matched."""
    raw = "Just some generic text block without headings"
    sections = parse_sections(raw, source_type="generic")
    assert len(sections) == 1
    assert sections[0]["sectionType"] == "generic_section"


def test_embedding_formatter():
    """Test structured embedding formatting."""
    chunk = {
        "chunkText": "Developed the main backend RAG search endpoint.",
        "sectionTitle": "InternPath",
        "sectionType": "project_experience",
        "semanticType": "experience",
        "keywords": ["Python", "FastAPI", "RAG"],
        "sourceType": "resume"
    }
    fmt = format_embedding_text(chunk)
    assert "Section: InternPath" in fmt
    assert "Semantic Type: Experience" in fmt
    assert "Skills: Python, FastAPI, RAG" in fmt
    assert "Content:" in fmt


def test_metadata_chunking_inheritance():
    """Test chunks inherit parent section properties and respect boundaries."""
    doc = """
    # 工作经历
    我在字节跳动研发了推荐算法。
    # 专业技能
    掌握 Python 和 PyTorch。
    """
    chunks = chunk_document_with_sections(
        content=doc,
        document_id="doc-1",
        file_name="resume.md",
        source_type="resume",
        chunk_size=100,
        overlap=10
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert c["documentId"] == "doc-1"
        assert c["fileName"] == "resume.md"
        assert c["sourceType"] == "resume"
        assert "embeddingText" in c
        assert "metadata" in c
        assert "keywords" in c
        
    bytedance_chunk = next(c for c in chunks if "字节跳动" in c["chunkText"])
    assert bytedance_chunk["sectionType"] == "work_experience"
    assert bytedance_chunk["semanticType"] == "experience"
    assert bytedance_chunk["importance"] == 0.90


def test_char_bigram_similarity():
    """Test Jaccard character bigram soft matching."""
    s1 = "Python FastAPI"
    s2 = "We built a FastAPI backend using Python."
    sim = char_bigram_similarity(s1, s2)
    assert sim > 0.0
    
    s3 = "Unrelated words here"
    assert char_bigram_similarity(s1, s3) < sim


def test_hybrid_retrieval():
    """Test Hybrid retrieval score combining BM25 and boosts."""
    chunks = [
        {
            "chunkId": "c1",
            "documentId": "doc1",
            "text": "Looking for Python FastAPI backend developers.",
            "chunkText": "Looking for Python FastAPI backend developers.",
            "sectionTitle": "任职要求",
            "sectionType": "job_requirements",
            "semanticType": "skills",
            "importance": 0.95,
            "keywords": ["Python", "FastAPI"],
            "sourceType": "jd"
        },
        {
            "chunkId": "c2",
            "documentId": "doc1",
            "text": "This is just a self introduction block.",
            "chunkText": "This is just a self introduction block.",
            "sectionTitle": "自我介绍",
            "sectionType": "self_introduction",
            "semanticType": "general",
            "importance": 0.50,
            "keywords": ["self", "intro"],
            "sourceType": "resume"
        }
    ]
    results = retrieve_hybrid(chunks, "Python FastAPI backend developer", 2)
    assert len(results) == 2
    assert results[0]["chunkId"] == "c1"
    assert results[0]["score"] > results[1]["score"]
    assert "bm25_match" in results[0]["retrievalReasons"]
    assert "keyword_match" in results[0]["retrievalReasons"]


def test_semantic_ranking():
    """Test Reranking boosts semantic type and hierarchy matches."""
    chunks = [
        {
            "chunkId": "c1",
            "documentId": "d1",
            "text": "Self introductory details about programming.",
            "sectionTitle": "自我介绍",
            "sectionType": "self_introduction",
            "semanticType": "general",
            "importance": 0.50,
            "hierarchy": ["自我介绍"],
            "score": 0.80
        },
        {
            "chunkId": "c2",
            "documentId": "d1",
            "text": "I developed recommender systems at ByteDance using PyTorch.",
            "sectionTitle": "字节跳动",
            "sectionType": "work_experience",
            "semanticType": "experience",
            "importance": 0.90,
            "hierarchy": ["工作经历", "字节跳动"],
            "score": 0.60
        }
    ]
    
    # Query implies experience requirement
    ranked = rerank_chunks(chunks, "字节跳动推荐算法项目经历", 2)
    assert ranked[0]["chunkId"] == "c2"  # Boosted based on experience type and hierarchy match!


def test_claim_evidence_checker_constraint():
    """Test strict section-type constraints mapping claims to experience sections."""
    chunks = [
        {
            "chunkId": "c1",
            "documentId": "d1",
            "chunkText": "I have brief interests in PyTorch.",
            "sectionType": "self_introduction",
            "sectionTitle": "自我介绍",
            "hierarchy": ["自我介绍"],
            "keywords": ["pytorch"]
        }
    ]
    
    # Claim: "具备 PyTorch 推荐算法实战经验"
    # Even though "pytorch" keyword matches chunk, chunk is in self_introduction (not experience section!)
    # Hence it must map to UNSUPPORTED or WEAK.
    claims = ["具备 PyTorch 推荐算法实战经验"]
    results = verify_claims_section_aware(claims, chunks)
    assert len(results) == 1
    assert results[0]["status"] in ("weak", "unsupported")
