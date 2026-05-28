"""Section-aware parsing for Resume, JD, Markdown, and General documents."""

import re
from typing import Any, Dict, List, Optional

# Standard importance mapping for sections
SECTION_IMPORTANCE = {
    # Resume types
    "education": 0.80,
    "project_experience": 0.95,
    "work_experience": 0.90,
    "skills": 0.85,
    "open_source": 0.80,
    "research": 0.85,
    "awards": 0.70,
    "contact": 0.60,
    "self_introduction": 0.50,
    
    # JD types
    "job_responsibilities": 0.90,
    "job_requirements": 0.95,
    "preferred_skills": 0.80,
    "tech_stack": 0.85,
    "education_requirement": 0.75,
    "work_location": 0.60,
    "company_intro": 0.50,
    
    # Generic fallback
    "generic_section": 0.60
}


def classify_section_type(title: str, is_jd: bool = False) -> str:
    """Classify a section title to standard sectionType."""
    title_clean = title.strip().lower()
    
    if is_jd:
        if any(w in title_clean for w in ("职责", "负责", "工作内容", "responsibilit", "duties", "what you will do")):
            return "job_responsibilities"
        if any(w in title_clean for w in ("要求", "资格", "条件", "requirement", "qualification", "what we look for", "skills required")):
            return "job_requirements"
        if any(w in title_clean for w in ("优先", "加分", "plus", "bonus", "preferred")):
            return "preferred_skills"
        if any(w in title_clean for w in ("技术栈", "技术要求", "开发环境", "tech stack")):
            return "tech_stack"
        if any(w in title_clean for w in ("学历", "教育", "degree", "education")):
            return "education_requirement"
        if any(w in title_clean for w in ("地点", "城市", "location")):
            return "work_location"
        if any(w in title_clean for w in ("公司介绍", "关于我们", "关于公司", "about us", "company profile")):
            return "company_intro"
        return "generic_section"
    
    # Resume classification
    if any(w in title_clean for w in ("教育", "学校", "学历", "毕业", "就读", "education", "academic", "university", "school", "degree")):
        return "education"
    if any(w in title_clean for w in ("项目经历", "项目经验", "研发项目", "projects", "project experience", "personal projects")):
        return "project_experience"
    if any(w in title_clean for w in ("工作经历", "实习经历", "工作经验", "实习经验", "职业经历", "work experience", "employment", "professional experience", "internship", "career")):
        return "work_experience"
    if any(w in title_clean for w in ("专业技能", "技能证书", "技能栈", "技术栈", "专业能力", "特长", "skills", "technical skills", "certifications", "certificates")):
        return "skills"
    if any(w in title_clean for w in ("开源", "社区贡献", "open source")):
        return "open_source"
    if any(w in title_clean for w in ("科研", "学术成果", "研究成果", "论文", "research", "publications")):
        return "research"
    if any(w in title_clean for w in ("获奖", "荣誉", "证书", "竞赛", "awards", "honors")):
        return "awards"
    if any(w in title_clean for w in ("联系方式", "个人信息", "联系我", "contact", "personal details", "phone", "email")):
        return "contact"
    if any(w in title_clean for w in ("自我评价", "自我介绍", "评价", "个人简介", "summary", "objective", "about me", "self introduction", "profile")):
        return "self_introduction"
        
    return "generic_section"


def parse_sections(text: str, source_type: str = "generic") -> List[Dict[str, Any]]:
    """
    Parse a document into structured sections.
    Supports markdown headings, plain text resumes, or JDs.
    """
    if not text or not text.strip():
        return []
        
    is_jd = (source_type.lower() == "jd")
    is_resume = (source_type.lower() == "resume")
    
    # Pre-check: is it Markdown?
    lines = text.splitlines()
    has_markdown_headings = any(line.strip().startswith("#") for line in lines[:100])
    
    sections: List[Dict[str, Any]] = []
    
    if has_markdown_headings:
        # Markdown Parsing Engine
        current_section: Optional[Dict[str, Any]] = None
        heading_stack: List[Dict[str, Any]] = []  # keeps track of levels [ {"id": ..., "title": ..., "level": ...} ]
        
        idx = 0
        section_content_lines: List[str] = []
        
        for line in lines:
            stripped = line.strip()
            # Detect Markdown Header
            match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if match:
                # Flush previous section
                if current_section:
                    current_section["content"] = "\n".join(section_content_lines).strip()
                    sections.append(current_section)
                    section_content_lines = []
                
                level = len(match.group(1))
                title = match.group(2).strip()
                sec_id = f"sec-{source_type}-{idx}"
                idx += 1
                
                # Keep stack consistent
                while heading_stack and heading_stack[-1]["level"] >= level:
                    heading_stack.pop()
                    
                parent_id = heading_stack[-1]["sectionId"] if heading_stack else None
                
                # Build hierarchy
                hierarchy = [h["title"] for h in heading_stack] + [title]
                
                sec_type = classify_section_type(title, is_jd=is_jd)
                importance = SECTION_IMPORTANCE.get(sec_type, 0.60)
                
                current_section = {
                    "sectionId": sec_id,
                    "sectionType": sec_type,
                    "title": title,
                    "content": "",
                    "importance": importance,
                    "level": level,
                    "parentSectionId": parent_id,
                    "hierarchy": hierarchy
                }
                
                heading_stack.append({"sectionId": sec_id, "title": title, "level": level})
            else:
                if current_section:
                    section_content_lines.append(line)
                else:
                    # Content before any header: create a generic header
                    sec_id = f"sec-{source_type}-pre"
                    sec_type = "generic_section"
                    current_section = {
                        "sectionId": sec_id,
                        "sectionType": sec_type,
                        "title": "Introduction",
                        "content": "",
                        "importance": SECTION_IMPORTANCE[sec_type],
                        "level": 1,
                        "parentSectionId": None,
                        "hierarchy": ["Introduction"]
                    }
                    section_content_lines.append(line)
                    
        if current_section:
            current_section["content"] = "\n".join(section_content_lines).strip()
            sections.append(current_section)
            
    else:
        # Plain text Resume or JD Parsing (using heuristic header lines)
        # Check lines that look like heading lines
        header_patterns = [
            # Chinese
            r"^(教育经历|教育背景|毕业院校|就读经历|学习经历|Education|Academic Background)$",
            r"^(项目经历|项目经验|研发项目|实践经历|Projects|Project Experience)$",
            r"^(工作经历|实习经历|工作经验|实习经验|职业经历|Work Experience|Employment|Professional Experience|Internship)$",
            r"^(专业技能|技能证书|技能栈|技术栈|专业能力|技能特长|Skills|Technical Skills|Certifications)$",
            r"^(开源经历|社区贡献|Open Source)$",
            r"^(科研经历|科研项目|学术成果|论文发表|Research)$",
            r"^(获奖证书|获奖经历|荣誉奖励|Awards|Honors)$",
            r"^(联系方式|联系我|个人信息|Contact Information|Personal Info)$",
            r"^(自我评价|自我介绍|个人总结|评价|About Me|Summary|Self Introduction)$",
            # JD specific
            r"^(岗位职责|工作职责|职责描述|Responsibilities|Duties|What you will do)$",
            r"^(任职要求|任职资格|岗位要求|招聘条件|职位要求|Requirements|Qualifications|What we look for|Skills Required)$",
            r"^(加分项|优先考虑|优先条件|Preferred Skills|Plus|Bonus)$",
            r"^(技术栈|技术要求|Tech Stack)$",
            r"^(关于公司|公司介绍|关于我们|About Us|Company Profile)$"
        ]
        
        combined_header_re = re.compile("|".join(header_patterns), re.IGNORECASE)
        
        current_section = None
        section_content_lines = []
        idx = 0
        
        for line in lines:
            stripped = line.strip()
            # If the line looks exactly like a section heading or is bold/short
            # A line is treated as header if it matches patterns and is reasonably short (<=20 chars)
            if combined_header_re.match(stripped) and len(stripped) <= 30:
                # Flush previous section
                if current_section:
                    current_section["content"] = "\n".join(section_content_lines).strip()
                    sections.append(current_section)
                    section_content_lines = []
                    
                sec_id = f"sec-{source_type}-{idx}"
                idx += 1
                sec_type = classify_section_type(stripped, is_jd=is_jd)
                importance = SECTION_IMPORTANCE.get(sec_type, 0.60)
                
                current_section = {
                    "sectionId": sec_id,
                    "sectionType": sec_type,
                    "title": stripped,
                    "content": "",
                    "importance": importance,
                    "level": 1,
                    "parentSectionId": None,
                    "hierarchy": [stripped]
                }
            else:
                if current_section:
                    section_content_lines.append(line)
                else:
                    # Content before any header
                    sec_id = f"sec-{source_type}-pre"
                    sec_type = "generic_section"
                    current_section = {
                        "sectionId": sec_id,
                        "sectionType": sec_type,
                        "title": "General Info",
                        "content": "",
                        "importance": SECTION_IMPORTANCE[sec_type],
                        "level": 1,
                        "parentSectionId": None,
                        "hierarchy": ["General Info"]
                    }
                    section_content_lines.append(line)
                    
        if current_section:
            current_section["content"] = "\n".join(section_content_lines).strip()
            sections.append(current_section)
            
    # Clean and filter sections (keep sections that actually have some content)
    valid_sections = []
    for sec in sections:
        if sec["content"].strip():
            valid_sections.append(sec)
            
    # Guarantee fallback if no sections could be formed
    if not valid_sections:
        sec_type = "generic_section"
        valid_sections.append({
            "sectionId": f"sec-{source_type}-fallback",
            "sectionType": sec_type,
            "title": "Document Content",
            "content": text.strip(),
            "importance": SECTION_IMPORTANCE[sec_type],
            "level": 1,
            "parentSectionId": None,
            "hierarchy": ["Document Content"]
        })
        
    return valid_sections
