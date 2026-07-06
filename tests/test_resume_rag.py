from backend.resume_rag import clean_resume_text, chunk_resume, repair_resume_chunk_sections, section_for_line


def test_clean_resume_text_preserves_section_headings():
    raw_text = """张三
13800000000
zhangsan@example.com

教育经历
北京大学 计算机科学与技术 本科

专业技能
Python, FastAPI, React, Docker

项目经历
InternPath 实习助手
负责 Agent 简历优化链路。
"""

    cleaned = clean_resume_text(raw_text)
    chunks = chunk_resume(cleaned, "resume-1", "resume.pdf")
    sections = {chunk["section"] for chunk in chunks}

    assert "教育经历" in sections
    assert "技能" in sections
    assert "项目经历" in sections
    assert sections != {"其他"}
    assert all(chunk["sectionType"] != "generic_section" for chunk in chunks if chunk["section"] != "其他")


def test_section_for_line_accepts_inline_and_decorated_headings():
    assert section_for_line("## 项目经历") == "项目经历"
    assert section_for_line("专业技能：Python / TypeScript / RAG") == "技能"
    assert section_for_line("Work Experience - Backend Intern") == "实习 / 工作经历"
    assert section_for_line("项目经历包括接口开发和性能优化") is None


def test_chunk_resume_exposes_structured_section_metadata_for_retrieval():
    text = clean_resume_text(
        """基本信息
李四 13800000000
技术能力 Python SQL Docker
工作经验 后端开发实习，负责 FastAPI 接口与 Redis 缓存。"""
    )

    chunks = chunk_resume(text, "resume-2", "resume.docx")

    assert [chunk["section"] for chunk in chunks] == ["基本信息", "技能", "实习 / 工作经历"]
    assert chunks[1]["sectionType"] == "skills"
    assert chunks[1]["semanticType"] == "skills"
    assert chunks[2]["sectionType"] == "work_experience"
    assert chunks[2]["metadata"]["sectionTitle"] == "实习 / 工作经历"


def test_chunk_resume_recovers_sections_from_flattened_pdf_text():
    raw_text = (
        "王五 13800000000 wangwu@example.com "
        "教育背景 北京大学 软件工程 本科 2022-2026 "
        "专业技能 Python FastAPI React Docker "
        "项目经历 InternPath 实习助手 负责 RAG 检索与分析流程。 "
        "工作经历 后端开发实习 负责 Redis 缓存和接口性能优化。"
    )

    cleaned = clean_resume_text(raw_text)
    chunks = chunk_resume(cleaned, "resume-flat", "resume.pdf")
    sections = [chunk["section"] for chunk in chunks]

    assert sections == ["其他", "教育经历", "技能", "项目经历", "实习 / 工作经历"]
    assert [chunk["sectionType"] for chunk in chunks[1:]] == [
        "education",
        "skills",
        "project_experience",
        "work_experience",
    ]
    assert "项目经历包括接口开发和性能优化" not in cleaned


def test_repair_resume_chunk_sections_rebuilds_legacy_generic_chunks():
    parsed_resume = {
        "file": {"id": "resume-old", "name": "resume.pdf", "size": 1024, "type": "application/pdf"},
        "cleanedText": (
            "李四 13800000000 "
            "教育经历 浙江大学 计算机科学 本科 "
            "技术能力 Python SQL Docker "
            "项目经验 数据分析平台 负责 ETL 和可视化。"
        ),
        "chunks": [
            {
                "id": "legacy-0",
                "resumeFileId": "resume-old",
                "index": 0,
                "content": "李四 13800000000 教育经历 浙江大学 计算机科学 本科 技术能力 Python SQL Docker 项目经验 数据分析平台 负责 ETL 和可视化。",
                "section": "其他",
                "sectionType": "generic_section",
                "semanticType": "general",
            }
        ],
    }

    repaired, changed = repair_resume_chunk_sections(parsed_resume)
    chunks = repaired["chunks"]

    assert changed is True
    assert [chunk["section"] for chunk in chunks] == ["其他", "教育经历", "技能", "项目经历"]
    assert all(chunk["sectionType"] != "generic_section" for chunk in chunks if chunk["section"] != "其他")
    assert chunks[2]["metadata"]["semanticType"] == "skills"
