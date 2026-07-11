import io
from zipfile import ZIP_DEFLATED, ZipFile

from backend.resume_rag import (
    build_resume_blocks,
    clean_resume_text,
    chunk_resume,
    parse_resume,
    repair_resume_chunk_sections,
    section_for_line,
)
from document_parser import extract_docx_structure


def _docx_bytes(document_xml: str) -> bytes:
    payload = io.BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return payload.getvalue()


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


def test_repair_resume_chunk_sections_rebuilds_legacy_generic_blocks_too():
    parsed_resume = {
        "file": {"id": "resume-old", "name": "resume.docx", "size": 1024, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "cleanedText": (
            "李四 13800000000\n"
            "教育及培训 浙江大学 计算机科学 本科\n"
            "专业能力 Python SQL Docker\n"
            "项目/实践 数据分析平台 负责 ETL 和可视化。"
        ),
        "chunks": [
            {"id": "legacy-0", "content": "李四 13800000000", "section": "其他", "sectionType": "generic_section"},
        ],
        "blocks": [
            {"id": "legacy-block-1", "text": "教育及培训 浙江大学 计算机科学 本科", "sectionName": "其他", "sectionId": "generic_section"},
            {"id": "legacy-block-2", "text": "项目/实践 数据分析平台 负责 ETL 和可视化。", "sectionName": "其他", "sectionId": "generic_section"},
        ],
    }

    repaired, changed = repair_resume_chunk_sections(parsed_resume)

    assert changed is True
    assert [block["sectionName"] for block in repaired["blocks"]] == [
        "其他", "教育经历", "技能", "项目经历",
    ]
    assert all(block["sectionId"] != "generic_section" for block in repaired["blocks"][1:])


def test_repair_resume_chunk_sections_repairs_generic_blocks_when_chunks_are_already_classified():
    parsed_resume = {
        "file": {"id": "resume-old", "name": "resume.pdf", "size": 1024, "type": "application/pdf"},
        "cleanedText": "教育经历\n浙江大学 计算机科学 本科\n项目经历\nInternPath 负责接口开发",
        "chunks": [
            {"id": "chunk-1", "content": "教育经历\n浙江大学 计算机科学 本科", "section": "教育经历", "sectionType": "education"},
            {"id": "chunk-2", "content": "项目经历\nInternPath 负责接口开发", "section": "项目经历", "sectionType": "project_experience"},
        ],
        "blocks": [
            {"id": "legacy-block-1", "text": "教育经历", "sectionName": "其他", "sectionId": "generic_section"},
            {"id": "legacy-block-2", "text": "InternPath 负责接口开发", "sectionName": "其他", "sectionId": "generic_section"},
        ],
    }

    repaired, changed = repair_resume_chunk_sections(parsed_resume)

    assert changed is True
    assert [block["sectionName"] for block in repaired["blocks"]] == ["教育经历", "教育经历", "项目经历", "项目经历"]


def test_repair_resume_chunk_sections_repairs_partially_generic_legacy_content_with_known_headings():
    parsed_resume = {
        "file": {"id": "resume-old", "name": "resume.pdf", "size": 1024, "type": "application/pdf"},
        "cleanedText": "教育经历\n浙江大学 计算机科学 本科\n项目经历\nInternPath 负责 FastAPI 接口开发",
        "chunks": [
            {"id": "chunk-education", "content": "教育经历\n浙江大学 计算机科学 本科", "section": "教育经历", "sectionType": "education"},
            {"id": "chunk-project", "content": "项目经历\nInternPath 负责 FastAPI 接口开发", "section": "其他", "sectionType": "generic_section"},
        ],
        "blocks": [
            {"id": "block-education", "text": "教育经历", "sectionName": "教育经历", "sectionId": "education"},
            {"id": "block-project", "text": "InternPath 负责 FastAPI 接口开发", "sectionName": "其他", "sectionId": "generic_section"},
        ],
    }

    repaired, changed = repair_resume_chunk_sections(parsed_resume)

    assert changed is True
    assert [chunk["section"] for chunk in repaired["chunks"]] == ["教育经历", "项目经历"]
    assert all(block["sectionName"] != "其他" for block in repaired["blocks"])


def test_build_resume_blocks_uses_stable_context_and_honest_locator_confidence():
    text = clean_resume_text(
        """项目经历
InternPath
- 负责 FastAPI 接口开发
- 使用 Redis 缓存热点数据"""
    )

    first = build_resume_blocks(text, "resume-1", "resume.docx")
    second = build_resume_blocks(text, "resume-1", "resume.docx")

    assert [block["id"] for block in first] == [block["id"] for block in second]
    bullet = next(block for block in first if block["kind"] == "bullet")
    assert bullet["sectionName"] == "项目经历"
    assert bullet["contextBefore"]
    assert bullet["locator"]["sourceFormat"] == "docx"
    assert bullet["locatorConfidence"] == "approximate"


def test_parse_resume_builds_docx_markdown_and_chunks_from_native_structure():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>项目经历</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>负责 FastAPI 接口开发</w:t></w:r></w:p>
            <w:tbl><w:tr>
              <w:tc><w:p><w:r><w:t>技术栈</w:t></w:r></w:p></w:tc>
              <w:tc><w:p><w:r><w:t>Python / Redis</w:t></w:r></w:p></w:tc>
            </w:tr></w:tbl>
          </w:body>
        </w:document>""",
    )

    parsed = parse_resume(
        "resume.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data,
    )

    assert "## 项目经历" in parsed["structuredMarkdown"]
    assert "- 负责 FastAPI 接口开发" in parsed["structuredMarkdown"]
    assert "| 技术栈 | Python / Redis |" in parsed["structuredMarkdown"]
    assert [block["kind"] for block in parsed["blocks"]] == ["heading", "bullet", "table_cell"]
    assert parsed["blocks"][0]["locator"]["paragraphIndex"] == 0
    assert parsed["blocks"][-1]["locator"]["tableIndex"] == 0
    assert parsed["chunks"][0]["sourceBlockIds"]


def test_docx_duplicate_paragraphs_are_merged_before_markdown_preview_and_rag():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>项目经历</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>负责 FastAPI 接口开发</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>负责 FastAPI 接口开发</w:t></w:r></w:p>
          </w:body>
        </w:document>""",
    )

    parsed = parse_resume(
        "resume.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data,
    )

    bullet = next(block for block in parsed["blocks"] if block["kind"] == "bullet")
    assert sum(block["text"] == "负责 FastAPI 接口开发" for block in parsed["blocks"]) == 1
    assert len(bullet["sourceBlockIds"]) == 2
    assert parsed["structuredMarkdown"].count("负责 FastAPI 接口开发") == 1
    assert "\n".join(chunk["content"] for chunk in parsed["chunks"]).count("负责 FastAPI 接口开发") == 1


def test_structured_block_and_chunk_ids_are_stable_when_the_same_file_is_uploaded_again():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>项目经历</w:t></w:r></w:p>
          <w:p><w:r><w:t>InternPath：负责 FastAPI 接口开发</w:t></w:r></w:p></w:body>
        </w:document>""",
    )

    first = parse_resume("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)
    second = parse_resume("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)

    assert [block["id"] for block in first["blocks"]] == [block["id"] for block in second["blocks"]]
    assert [chunk["id"] for chunk in first["chunks"]] == [chunk["id"] for chunk in second["chunks"]]


def test_docx_alternate_content_reads_one_branch_and_emits_textbox_paragraphs_individually():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
          xmlns:v="urn:schemas-microsoft-com:vml">
          <w:body>
            <w:p>
              <mc:AlternateContent>
                <mc:Choice Requires="wps"><w:drawing><wps:wsp><wps:txbx><w:txbxContent>
                  <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
                  <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
                </w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice>
                <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>
                  <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
                  <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
                </w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
              </mc:AlternateContent>
              <mc:AlternateContent>
                <mc:Choice Requires="wps"><w:drawing><wps:wsp><wps:txbx><w:txbxContent>
                  <w:p><w:r><w:t>项目经历</w:t></w:r></w:p>
                  <w:p><w:r><w:t>InternPath 负责接口开发</w:t></w:r></w:p>
                </w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice>
                <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>
                  <w:p><w:r><w:t>项目经历</w:t></w:r></w:p>
                  <w:p><w:r><w:t>InternPath 负责接口开发</w:t></w:r></w:p>
                </w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
              </mc:AlternateContent>
            </w:p>
          </w:body>
        </w:document>""",
    )

    records = extract_docx_structure(data)
    parsed = parse_resume("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)

    assert [record["text"] for record in records] == [
        "教育背景",
        "暨南大学 软件工程",
        "项目经历",
        "InternPath 负责接口开发",
    ]
    assert all(record["locator"].get("textboxIndex") is not None for record in records)
    assert sum(block["text"] == "教育背景" for block in parsed["blocks"]) == 1
    assert sum(block["text"] == "项目经历" for block in parsed["blocks"]) == 1
    assert parsed["structuredMarkdown"].count("教育背景") == 1
    assert parsed["structuredMarkdown"].count("项目经历") == 1


def test_legacy_resume_with_original_docx_is_reparsed_by_the_current_structured_parser():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
          xmlns:v="urn:schemas-microsoft-com:vml">
          <w:body><w:p><mc:AlternateContent>
            <mc:Choice Requires="wps"><w:drawing><wps:wsp><wps:txbx><w:txbxContent>
              <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
              <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
            </w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice>
            <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>
              <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
              <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
            </w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
          </mc:AlternateContent></w:p></w:body>
        </w:document>""",
    )
    current = parse_resume("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)
    legacy = {
        **current,
        "structureVersion": None,
        "parser": None,
        "file": {**current["file"], "id": "resume-existing"},
        "cleanedText": "教育背景教育背景 暨南大学 软件工程 暨南大学 软件工程",
        "blocks": [
            {
                "id": "legacy-duplicate", "kind": "paragraph", "sectionId": "generic_section", "sectionName": "其他",
                "text": "教育背景教育背景 暨南大学 软件工程 暨南大学 软件工程", "textHash": "old",
                "locationLabel": "其他 > 第 1 条", "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
            }
        ],
    }

    repaired, changed = repair_resume_chunk_sections(legacy)

    assert changed is True
    assert repaired["file"]["id"] == "resume-existing"
    assert repaired["parser"]["version"] == "v2"
    assert [block["text"] for block in repaired["blocks"]] == ["教育背景", "暨南大学 软件工程"]


def test_docx_table_cell_textboxes_use_extractable_fallback_and_remain_leaf_blocks():
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:v="urn:schemas-microsoft-com:vml">
          <w:body><w:tbl><w:tr><w:tc><w:p><mc:AlternateContent>
            <mc:Choice Requires="unsupported"><w:drawing/></mc:Choice>
            <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>
              <w:p><w:r><w:t>技能证书</w:t></w:r></w:p>
              <w:p><w:r><w:t>大学英语六级证书</w:t></w:r></w:p>
            </w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
          </mc:AlternateContent></w:p></w:tc></w:tr></w:tbl></w:body>
        </w:document>""",
    )

    records = extract_docx_structure(data)

    assert [record["text"] for record in records] == ["技能证书", "大学英语六级证书"]
    assert all(record["locator"]["tableIndex"] == 0 for record in records)
    assert all(record["locator"]["cellIndex"] == 0 for record in records)
    assert all(record["locator"].get("textboxIndex") is not None for record in records)
