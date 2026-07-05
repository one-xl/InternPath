from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
from typing import Any, Optional

from backend.agents.tools.workspace_tools import get_safe_workspace_path


def extract_docx_style_profile(user_id: Any, task_id: str, original_resume_id: Optional[str]) -> None:
    """
    从用户上传的原始简历中提取格式信息并保存到工作区中的 style_profile.json。
    """
    from database import Database

    profile = {
        "body_font": "SimSun",
        "body_size": 11.0,
        "line_spacing": 1.15,
        "space_after": 6.0,
        "space_before": 0.0,
        "margins": {
            "top": 2.0,
            "bottom": 2.0,
            "left": 2.5,
            "right": 2.5,
        },
        "heading_font": "SimSun",
        "heading_size": 14.0,
    }

    if original_resume_id:
        db = Database()
        resume_data = db.get_user_resume(user_id, original_resume_id)
        if resume_data and "file" in resume_data:
            b64_data = resume_data["file"].get("b64_content", "")
            file_name = resume_data["file"].get("name", "")
            suffix = os.path.splitext(file_name)[1].lower()

            if b64_data:
                try:
                    file_bytes = base64.b64decode(b64_data)
                    if suffix == ".docx":
                        orig_docx_path = get_safe_workspace_path(user_id, task_id, "original_resume.docx")
                        with open(orig_docx_path, "wb") as f:
                            f.write(file_bytes)
                        import docx

                        doc = docx.Document(io.BytesIO(file_bytes))
                        body_fonts: dict[str, int] = {}
                        body_sizes: dict[float, int] = {}
                        heading_fonts: dict[str, int] = {}
                        heading_sizes: dict[float, int] = {}

                        for paragraph in doc.paragraphs:
                            is_heading = paragraph.style.name.startswith("Heading") or paragraph.style.name.startswith("Title")
                            p_format = paragraph.paragraph_format
                            if p_format.line_spacing is not None and isinstance(p_format.line_spacing, (int, float)):
                                profile["line_spacing"] = round(p_format.line_spacing, 2)
                            if p_format.space_after is not None:
                                profile["space_after"] = round(p_format.space_after.pt, 1)
                            if p_format.space_before is not None:
                                profile["space_before"] = round(p_format.space_before.pt, 1)

                            for run in paragraph.runs:
                                if run.font.name:
                                    target = heading_fonts if is_heading else body_fonts
                                    target[run.font.name] = target.get(run.font.name, 0) + 1
                                if run.font.size:
                                    size = run.font.size.pt
                                    target = heading_sizes if is_heading else body_sizes
                                    target[size] = target.get(size, 0) + 1

                        if body_fonts:
                            profile["body_font"] = max(body_fonts, key=body_fonts.get)
                        if body_sizes:
                            profile["body_size"] = max(body_sizes, key=body_sizes.get)
                        if heading_fonts:
                            profile["heading_font"] = max(heading_fonts, key=heading_fonts.get)
                        if heading_sizes:
                            profile["heading_size"] = max(heading_sizes, key=heading_sizes.get)

                        if doc.sections:
                            section = doc.sections[0]
                            profile["margins"] = {
                                "top": round(section.top_margin.cm, 2) if section.top_margin else 2.0,
                                "bottom": round(section.bottom_margin.cm, 2) if section.bottom_margin else 2.0,
                                "left": round(section.left_margin.cm, 2) if section.left_margin else 2.5,
                                "right": round(section.right_margin.cm, 2) if section.right_margin else 2.5,
                            }
                    elif suffix == ".pdf":
                        import pdfplumber

                        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                            body_fonts: dict[str, int] = {}
                            body_sizes: dict[float, int] = {}
                            for page in pdf.pages:
                                if not getattr(page, "chars", None):
                                    continue
                                for obj in page.chars:
                                    font = obj.get("fontname", "")
                                    size = obj.get("size", 11)
                                    if font:
                                        clean_font = font.split("+")[-1].split("-")[0]
                                        body_fonts[clean_font] = body_fonts.get(clean_font, 0) + 1
                                    if size:
                                        rounded_size = round(size * 2) / 2
                                        body_sizes[rounded_size] = body_sizes.get(rounded_size, 0) + 1

                            if body_fonts:
                                profile["body_font"] = max(body_fonts, key=body_fonts.get)
                            if body_sizes:
                                sorted_sizes = sorted(body_sizes.items(), key=lambda item: item[1], reverse=True)
                                profile["body_size"] = sorted_sizes[0][0]
                                headings = [
                                    size
                                    for size, count in sorted_sizes
                                    if size > profile["body_size"] and count > sorted_sizes[0][1] * 0.05
                                ]
                                if headings:
                                    profile["heading_size"] = max(headings)
                                    profile["heading_font"] = profile["body_font"]
                except Exception as exc:
                    print(f"[STYLE_EXTRACT_ERROR] Failed to extract style: {exc}")

    try:
        profile_path = get_safe_workspace_path(user_id, task_id, "style_profile.json")
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[STYLE_SAVE_ERROR] Failed to save style profile: {exc}")


def generate_docx_from_markdown(user_id: Any, task_id: str, markdown_content: str, docx_path: str) -> None:
    """
    根据 style_profile.json 生成样式保真的 DOCX 简历文件。
    """
    import docx
    from docx.shared import Cm, Pt

    profile = {
        "body_font": "SimSun",
        "body_size": 11,
        "line_spacing": 1.15,
        "space_after": 6.0,
        "space_before": 0.0,
        "margins": {
            "top": 2.0,
            "bottom": 2.0,
            "left": 2.5,
            "right": 2.5,
        },
        "heading_font": "SimSun",
        "heading_size": 14,
    }

    try:
        profile_path = get_safe_workspace_path(user_id, task_id, "style_profile.json")
        if os.path.exists(profile_path):
            with open(profile_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    profile.update(loaded)
    except Exception as exc:
        print(f"[DOCX_GEN_WARN] Failed to load style profile: {exc}")

    doc = docx.Document()
    if doc.sections:
        section = doc.sections[0]
        margins = profile.get("margins", {})
        section.top_margin = Cm(margins.get("top", 2.0))
        section.bottom_margin = Cm(margins.get("bottom", 2.0))
        section.left_margin = Cm(margins.get("left", 2.5))
        section.right_margin = Cm(margins.get("right", 2.5))

    blocks = re.split(r"\n\n+", markdown_content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", block)
        if heading_match:
            level = len(heading_match.group(1))
            title_text = heading_match.group(2)
            paragraph = doc.add_paragraph()
            p_format = paragraph.paragraph_format
            p_format.space_before = Pt(12)
            p_format.space_after = Pt(6)
            p_format.keep_with_next = True
            run = paragraph.add_run(title_text)
            run.bold = True
            run.font.name = profile.get("heading_font", "SimSun")
            run._r.get_or_add_rPr().get_or_add_rFonts().set(
                docx.oxml.ns.qn("w:eastAsia"),
                profile.get("heading_font", "SimSun"),
            )
            heading_size = profile.get("heading_size", 14)
            if level > 1:
                heading_size = max(heading_size - 2, 12)
            run.font.size = Pt(heading_size)
            continue

        list_match = re.match(r"^[\-\*\+]\s+(.*)$", block)
        if list_match:
            for line in block.splitlines():
                line_match = re.match(r"^[\-\*\+]\s+(.*)$", line.strip())
                paragraph = doc.add_paragraph(style="List Bullet" if line_match else None)
                p_format = paragraph.paragraph_format
                if not line_match:
                    p_format.left_indent = Cm(0.74)
                p_format.line_spacing = profile.get("line_spacing", 1.15)
                p_format.space_after = Pt(profile.get("space_after", 6.0))
                p_format.space_before = Pt(profile.get("space_before", 0.0))
                add_markdown_runs(paragraph, line_match.group(1) if line_match else line.strip(), profile)
            continue

        paragraph = doc.add_paragraph()
        p_format = paragraph.paragraph_format
        p_format.line_spacing = profile.get("line_spacing", 1.15)
        p_format.space_after = Pt(profile.get("space_after", 6.0))
        p_format.space_before = Pt(profile.get("space_before", 0.0))
        add_markdown_runs(paragraph, block, profile)

    doc.save(docx_path)


def add_markdown_runs(paragraph: Any, text: str, profile: dict[str, Any]) -> None:
    import docx
    from docx.shared import Pt

    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run_text = part[2:-2]
            is_bold = True
        else:
            run_text = part
            is_bold = False
        if not run_text:
            continue
        run = paragraph.add_run(run_text)
        run.bold = is_bold
        run.font.name = profile.get("body_font", "SimSun")
        run._r.get_or_add_rPr().get_or_add_rFonts().set(
            docx.oxml.ns.qn("w:eastAsia"),
            profile.get("body_font", "SimSun"),
        )
        run.font.size = Pt(profile.get("body_size", 11))


def convert_docx_to_pdf(user_id: Any, task_id: str, docx_path: str, pdf_dir: str) -> bool:
    """
    将 DOCX 转换为 PDF。优先使用 LibreOffice，回退到 docx2pdf。
    """
    libreoffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if libreoffice_bin:
        try:
            print(f"[PDF_CONVERT] Found LibreOffice at {libreoffice_bin}. Starting headless conversion...")
            result = subprocess.run(
                [libreoffice_bin, "--headless", "--convert-to", "pdf", "--outdir", pdf_dir, docx_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(os.path.join(pdf_dir, "optimized_resume.pdf")):
                print("[PDF_CONVERT] LibreOffice conversion succeeded.")
                return True
            print(f"[PDF_CONVERT] LibreOffice return code: {result.returncode}, stderr: {result.stderr}")
        except Exception as exc:
            print(f"[PDF_CONVERT] LibreOffice failed with exception: {exc}")

    try:
        from docx2pdf import convert

        print("[PDF_CONVERT] LibreOffice not found or failed. Falling back to docx2pdf...")
        pdf_path = os.path.join(pdf_dir, "optimized_resume.pdf")
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass
        convert(docx_path, pdf_path)
        if os.path.exists(pdf_path):
            print("[PDF_CONVERT] docx2pdf conversion succeeded.")
            return True
    except Exception as exc:
        print(f"[PDF_CONVERT] docx2pdf fallback failed: {exc}")

    return False


def update_docx_resume_from_log(user_id: Any, task_id: str) -> bool:
    """
    用 modification_log.json 中的修改记录对 original_resume.docx 原地替换，
    生成高保真的 optimized_resume.docx，并对表格/文本框做防溢出处理。
    """
    import docx

    orig_docx_path = get_safe_workspace_path(user_id, task_id, "original_resume.docx")
    opt_docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")
    mod_log_path = get_safe_workspace_path(user_id, task_id, "modification_log.json")

    if not os.path.exists(orig_docx_path):
        print(f"[DOCX_REPLACE] original_resume.docx not found at {orig_docx_path}. Skipping high-fidelity replacement.")
        return False
    if not os.path.exists(mod_log_path):
        print(f"[DOCX_REPLACE] modification_log.json not found at {mod_log_path}. Skipping.")
        return False

    try:
        shutil.copyfile(orig_docx_path, opt_docx_path)
        with open(mod_log_path, "r", encoding="utf-8") as f:
            modification_log = json.load(f)
        if not modification_log:
            print("[DOCX_REPLACE] modification_log.json is empty. No replacements needed.")
            return True

        doc = docx.Document(opt_docx_path)

        def get_all_paragraphs_with_textboxes(parent_doc: Any) -> list[Any]:
            paragraphs: list[Any] = []
            if hasattr(parent_doc, "paragraphs"):
                paragraphs.extend(parent_doc.paragraphs)
            if hasattr(parent_doc, "tables"):
                for table in parent_doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            paragraphs.extend(get_all_paragraphs_with_textboxes(cell))
            try:
                txbx_elements = parent_doc.element.xpath("//w:txbxContent")
                for txbx in txbx_elements:
                    for p_el in txbx.xpath(".//w:p"):
                        paragraphs.append(docx.text.paragraph.Paragraph(p_el, doc))
            except Exception as exc:
                print(f"[DOCX_REPLACE] Error searching textboxes: {exc}")
            return paragraphs

        def clean_text(text: str) -> str:
            return "".join(text.split()) if text else ""

        matched_count = 0
        for paragraph in get_all_paragraphs_with_textboxes(doc):
            paragraph_text_clean = clean_text(paragraph.text)
            if not paragraph_text_clean:
                continue
            for item in modification_log:
                original_clean = clean_text(item.get("original", ""))
                if not original_clean:
                    continue
                if (
                    original_clean == paragraph_text_clean
                    or original_clean in paragraph_text_clean
                    or paragraph_text_clean in original_clean
                ):
                    new_text = item.get("new", "")
                    alignment = paragraph.alignment
                    if paragraph.runs:
                        base_run = next((run for run in paragraph.runs if run.font.name or run.font.size), paragraph.runs[0])
                        font_name = base_run.font.name
                        font_size = base_run.font.size
                        font_color = base_run.font.color.rgb if (base_run.font.color and base_run.font.color.rgb) else None
                        bold = base_run.font.bold
                        italic = base_run.font.italic
                        underline = base_run.font.underline
                        paragraph.text = ""
                        run = paragraph.add_run(new_text)
                        if font_name:
                            run.font.name = font_name
                            try:
                                run._r.get_or_add_rPr().get_or_add_rFonts().set(docx.oxml.ns.qn("w:eastAsia"), font_name)
                            except Exception:
                                pass
                        if font_size:
                            run.font.size = font_size
                        if font_color:
                            run.font.color.rgb = font_color
                        if bold is not None:
                            run.font.bold = bold
                        if italic is not None:
                            run.font.italic = italic
                        if underline is not None:
                            run.font.underline = underline
                    else:
                        paragraph.text = new_text
                    if alignment is not None:
                        paragraph.alignment = alignment
                    matched_count += 1
                    break

        print(f"[DOCX_REPLACE] Replaced {matched_count} paragraphs in docx.")
        if matched_count == 0 and modification_log:
            print("[DOCX_REPLACE] No paragraph matched modification log; fallback generator should be used.")
            return False

        try:
            for shape in doc.element.xpath("//v:shape"):
                if shape.xpath(".//w:txbxContent"):
                    style = shape.get("style")
                    if style:
                        parts = []
                        has_fit = False
                        for part in style.split(";"):
                            part = part.strip()
                            if not part:
                                continue
                            if part.startswith("height:"):
                                parts.append("height:auto")
                            elif part.startswith("mso-fit-shape-to-text:"):
                                parts.append("mso-fit-shape-to-text:t")
                                has_fit = True
                            else:
                                parts.append(part)
                        if not has_fit:
                            parts.append("mso-fit-shape-to-text:t")
                        shape.set("style", ";".join(parts))
            print("[DOCX_REPLACE] Adjusted height attributes of VML textboxes.")
        except Exception as exc:
            print(f"[DOCX_REPLACE] Error processing VML textbox heights: {exc}")

        try:
            for table in doc.tables:
                for row in table.rows:
                    tr_pr = row._tr.get_or_add_trPr()
                    for cant_split in tr_pr.xpath("w:cantSplit"):
                        tr_pr.remove(cant_split)
                    for tr_height in tr_pr.xpath("w:trHeight"):
                        if tr_height.get(docx.oxml.ns.qn("w:hRule")) == "exact":
                            tr_height.set(docx.oxml.ns.qn("w:hRule"), "atLeast")
            print("[DOCX_REPLACE] Adjusted cantSplit and height rules for tables.")
        except Exception as exc:
            print(f"[DOCX_REPLACE] Error processing table rows: {exc}")

        doc.save(opt_docx_path)
        print(f"[DOCX_REPLACE] High-fidelity docx saved to {opt_docx_path}")
        return True
    except Exception as exc:
        import traceback

        print(f"[DOCX_REPLACE_ERROR] {exc}\n{traceback.format_exc()}")
        return False
