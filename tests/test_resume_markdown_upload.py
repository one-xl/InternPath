from backend.resume_rag import parse_resume


def test_markdown_resume_uses_text_parser_and_builds_blocks():
    parsed = parse_resume("resume.md", "text/markdown", b"# Project\n- Used Python and FastAPI\n")
    assert parsed["file"]["name"] == "resume.md"
    assert parsed["blocks"]
    assert "Python" in parsed["cleanedText"]
