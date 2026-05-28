"""Structured embedding text formatting helper."""

from typing import Any, Dict


def format_embedding_text(chunk: Dict[str, Any]) -> str:
    """
    Format a chunk's content together with its section metadata.
    Avoids vectorizing raw unstructured text directly, improving matching dramatically.
    """
    source_type = str(chunk.get("sourceType", chunk.get("source_type", "generic"))).lower()
    section_type = str(chunk.get("sectionType", chunk.get("section_type", "generic_section")))
    section_title = str(chunk.get("sectionTitle", chunk.get("section_title", "generic_section")))
    semantic_type = str(chunk.get("semanticType", chunk.get("semantic_type", "general")))
    keywords = chunk.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords_str = ", ".join(keywords) if keywords else "None"
    
    text = str(chunk.get("chunkText", chunk.get("text", ""))).strip()
    
    if source_type == "jd":
        # Format for Job Description
        role_req = ""
        pref_skills = ""
        resp = ""
        
        if "requirement" in section_type or "skills" in section_type:
            role_req = f"Role Requirement: Yes\nSkills Needed: {keywords_str}\n"
        if "preferred" in section_type or "bonus" in section_type:
            pref_skills = f"Preferred Skills: Yes\nBonus: {keywords_str}\n"
        if "responsibilities" in section_type or "duties" in section_type:
            resp = f"Responsibilities: Core Work Duties\n"
            
        formatted = f"Section Type: {section_type.upper()}\nSection Title: {section_title}\n{role_req}{pref_skills}{resp}\nContent:\n{text}"
        return formatted
        
    else:
        # Format for Resume or General Knowledge
        formatted = (
            f"Section: {section_title}\n"
            f"Semantic Type: {semantic_type.capitalize()}\n"
            f"Skills: {keywords_str}\n\n"
            f"Content:\n{text}"
        )
        return formatted
