import re
from typing import Any, Dict, List, Tuple

def tokenize_words(text: str) -> List[str]:
    """Simple tokenization splitting on spaces and punctuation, keeping English words and CJK characters."""
    return re.findall(r"[a-zA-Z0-9\-+#]+|[\u4e00-\u9fff]", text.lower())

def simulate_ats_compatibility(
    resume_text: str,
    file_name: str,
    jd_text: str = "",
    jd_skills: List[str] = None
) -> Dict[str, Any]:
    """Audits a resume's compatibility with typical Applicant Tracking Systems (ATS).
    
    Returns a dictionary with scores (0-100) and suggestions:
    - parseability_score: layout complexity, scanning text quality
    - structure_score: structural parsing risk (tables, multi-columns)
    - header_score: section tags standardness
    - keyword_density_score: overlap with JD keywords
    - overall_score: average of above
    """
    warnings = []
    suggestions = []
    
    # 1. Parseability & Formatting Audit
    char_count = len(resume_text.strip())
    if char_count < 50:
        # Very short text, likely a scanned PDF image or extraction error
        parseability_score = 20.0
        warnings.append("简历解析提取出的文本字数过少（少于 50 字），可能是纯图片扫描件，ATS 无法读取。")
        suggestions.append("请不要投递纯图片扫描件简历。请使用 Word 生成的 PDF 或文本型 PDF 进行投递。")
    else:
        # Standard text, check if we have too many raw symbols or unrecognized chars
        unknown_chars = len(re.findall(r"[\ufffd\u0000]", resume_text))
        if unknown_chars > 5:
            parseability_score = 60.0
            warnings.append(f"简历中包含较多乱码或特殊未知字符（{unknown_chars}个），可能影响系统检索。")
            suggestions.append("检查简历导出时的字体嵌入设置，避免使用非标准异体字。")
        else:
            parseability_score = 95.0

    # 2. Structure Complexity Audit
    # We audit multi-column layouts and layout parsing sequence by inspecting
    # excessive tabs or vertical pipes which often format tables or columns.
    structure_score = 100.0
    
    # Tab characters or long spaces separating columns
    tabs_count = len(re.findall(r"\t| {4,}", resume_text))
    vertical_pipes = len(re.findall(r"\|", resume_text))
    
    if vertical_pipes > 8:
        structure_score -= 20
        warnings.append("检测到较多垂直分割线（|），这通常意味着简历使用了复杂的表格或多栏布局。")
        suggestions.append("一些老旧的 ATS 系统在解析表格和双栏 PDF 时会导致排版阅读顺序错乱，建议使用单栏无表格版式。")
        
    if tabs_count > 15:
        structure_score -= 15
        warnings.append("检测到大量横向制表符或超长空格，可能是多列并排排版。")
        suggestions.append("排版时尽量使用标准的段落换行，避免在一行中并排放置不同的内容块。")
        
    structure_score = max(30.0, structure_score)

    # 3. Section Tag Standardness
    # ATS needs standard section headers (like Work Experience, Education, Projects)
    # to segment the resume.
    header_score = 100.0
    
    standard_headers = {
        "education": ["教育", "学习经历", "教育背景", "教育经历", "education"],
        "work": ["工作经历", "工作背景", "工作经历", "实习经历", "职业经历", "work experience", "experience", "employment"],
        "projects": ["项目经历", "项目经验", "研发项目", "项目背景", "projects", "project experience"],
        "skills": ["专业技能", "专业知识", "技术栈", "技能证书", "skills", "key skills"]
    }
    
    found_headers = {k: False for k in standard_headers}
    resume_lower = resume_text.lower()
    
    for section, aliases in standard_headers.items():
        for alias in aliases:
            # Match boundary words or separate lines containing the header
            pattern = rf"(?:^|\n)\s*{re.escape(alias)}\s*(?:\n|:|$)"
            if re.search(pattern, resume_lower):
                found_headers[section] = True
                break
                
    missing_sections = [k for k, found in found_headers.items() if not found]
    if missing_sections:
        deductions = len(missing_sections) * 20
        header_score -= deductions
        section_names_cn = {
            "education": "教育背景",
            "work": "工作经历",
            "projects": "项目经历",
            "skills": "专业技能"
        }
        for s in missing_sections:
            warnings.append(f"未检测到标准的 '{section_names_cn[s]}' 板块标题。")
            suggestions.append(f"在简历中添加清晰、标准的 '{section_names_cn[s]}' 标题，方便解析器定位。")
            
    header_score = max(20.0, header_score)

    # 4. Keyword Density
    # Calculate overlap and density against JD requirements.
    keyword_density_score = 100.0
    density = 0.0
    
    # Resolve target keywords
    target_keywords = set()
    if jd_skills:
        for skill in jd_skills:
            target_keywords.update(tokenize_words(skill))
    elif jd_text:
        # Extract potential keyword tokens from JD (English terms, capitalized terms, or typical technologies)
        jd_tokens = tokenize_words(jd_text)
        # Filter for typical keywords (e.g. English tokens or common technologies)
        # Keep alphanumeric tokens of length >= 2
        target_keywords = {t for t in jd_tokens if t.isalnum() and len(t) >= 2}
        
    if target_keywords:
        resume_tokens = tokenize_words(resume_text)
        total_tokens = len(resume_tokens) if resume_tokens else 1
        
        matches = [t for t in resume_tokens if t in target_keywords]
        unique_matches = set(matches)
        
        # Keyword density = matches / total tokens in resume
        density = len(matches) / total_tokens
        
        # Calculate score: optimal range is 2% - 5% (i.e. 0.02 - 0.05)
        if 0.02 <= density <= 0.05:
            keyword_density_score = 100.0
        elif density < 0.02:
            # Below 2%: lower score
            keyword_density_score = max(30.0, 100.0 - (0.02 - density) * 3500)
            warnings.append(f"核心关键词密度为 {density:.1%}，低于 ATS 筛选的推荐区间（2% - 5%）。")
            suggestions.append("在描述实习和项目时，适当重复提及职位描述中出现的技术词汇（如框架名、工具名）。")
        else:
            # Above 5%: keyword stuffing risk
            keyword_density_score = max(50.0, 100.0 - (density - 0.05) * 1500)
            warnings.append(f"核心关键词密度为 {density:.1%}，偏高（超过 5%），可能存在关键词堆砌嫌疑。")
            suggestions.append("优化关键词密度，使其自然融合在项目细节描述中，避免单纯在技能栏罗列。")
    else:
        density = 0.0
        keyword_density_score = 80.0 # No JD target to compare against

    # Calculate overall score
    overall_score = round((parseability_score + structure_score + header_score + keyword_density_score) / 4.0, 1)
    
    return {
        "parseability_score": parseability_score,
        "structure_score": structure_score,
        "header_score": header_score,
        "keyword_density_score": keyword_density_score,
        "overall_score": overall_score,
        "keyword_density": round(density, 4),
        "warnings": warnings,
        "suggestions": suggestions
    }
