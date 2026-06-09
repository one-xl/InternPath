from __future__ import annotations

import json
import math
import time
import hashlib
from typing import Any, Optional, Tuple

from database import Database
from service import CareerPathAIService
from ai_analyzer import AIAnalyzer, _strip_json_fence

# Module-level instances
db = Database()
service = CareerPathAIService()
analyzer = AIAnalyzer()

def cosine_similarity_py(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a)
    norm_b = sum(x * x for x in b)
    if not norm_a or not norm_b:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

def update_background_progress(
    user_id: Any,
    record_id: str,
    step_id: str,
    step_status: str,
    metadata: Optional[dict] = None,
    error_message: Optional[str] = None,
    overall_status: str = "processing"
) -> dict:
    record = db.get_analysis_record(user_id, record_id) or {}
    
    # Initialize steps list if not present
    if "steps" not in record:
        record["steps"] = [
            { "id": "validate", "title": "检查输入与配置", "description": "正在验证输入内容并加载模型配置...", "status": "pending" },
            { "id": "resume_embedding", "title": "向量化简历片段", "description": "正在生成简历片段的向量索引...", "status": "pending" },
            { "id": "jd_embedding", "title": "向量化岗位 JD", "description": "正在对岗位描述进行结构化分析与向量化...", "status": "pending" },
            { "id": "retrieve_chunks", "title": "检索最相关片段", "description": "基于语义相似度检索最匹配的简历经历...", "status": "pending" },
            { "id": "gemini_analysis", "title": "调用 Gemini 分析", "description": "大语言模型正在进行匹配度深度审计与改写建议...", "status": "pending" },
            { "id": "save_history", "title": "保存分析记录", "description": "保存分析数据至云端面板...", "status": "pending" }
        ]
        
    steps = record["steps"]
    
    # Update matching step
    for step in steps:
        if step["id"] == step_id:
            step["status"] = step_status
            if metadata is not None:
                if "metadata" not in step:
                    step["metadata"] = {}
                step["metadata"].update(metadata)
            if error_message is not None:
                step["errorMessage"] = error_message
            break
            
    # Calculate current progressStep
    progress_step = -1
    for idx, step in enumerate(steps):
        if step["status"] == "running":
            progress_step = idx
            break
    if progress_step == -1:
        for idx, step in enumerate(steps):
            if step["status"] == "pending":
                progress_step = idx
                break
                
    record["progressStep"] = progress_step
    
    # Save back to DB
    input_json = record.get("draft")
    db.save_analysis_record(
        user_id=user_id,
        status=overall_status,
        result_json=record,
        input_json=input_json,
        record_id=record_id
    )
    return record

_JD_PARSE_CACHE = {}
_HARD_CONSTRAINTS_CACHE = {}
_DEEP_ANALYSIS_CACHE = {}

def _limit_cache_size(cache_dict: dict, max_size: int = 1000):
    if len(cache_dict) > max_size:
        try:
            oldest_key = next(iter(cache_dict))
            cache_dict.pop(oldest_key, None)
        except StopIteration:
            pass

def parse_job_description_py(client: Any, model: str, jd_text: str) -> dict:
    jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
    cache_key = f"{jd_hash}:{model}"
    if cache_key in _JD_PARSE_CACHE:
        print(f"[BG_ANALYSIS] parse_job_description_py cache hit for key: {cache_key}")
        return _JD_PARSE_CACHE[cache_key]

    prompt = f"""
You are a rigorous JD analysis assistant. Your task is to split a Job Description into structural requirements and constraints.

Requirements:
- Split the JD into atomic, distinct requirements. Each requirement should have a unique id (e.g. req_001, req_002...).
- For each requirement, determine its priority: "must_have" vs "nice_to_have". Must-haves represent key requirements that are mandatory for passing the resume screen.
- Identify hard constraints such as degree level, years of experience, specific graduation date range, onsite/remote location, visa sponsorship, or key stack.
- Output valid JSON only conforming to the requested schema.

JD Text to parse:
{jd_text}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        content = response.choices[0].message.content
        parsed = json.loads(_strip_json_fence(content))
    except Exception as e:
        print(f"[BG_ANALYSIS] parseJobDescription JSON mode failed: {e}, retrying standard mode")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            content = response.choices[0].message.content
            parsed = json.loads(_strip_json_fence(content))
        except Exception as e2:
            print(f"[BG_ANALYSIS] parseJobDescription failed: {e2}")
            parsed = {}
            
    # Standardize output structure
    requirements = []
    raw_reqs = parsed.get("requirements") or []
    if isinstance(raw_reqs, list):
        for idx, r in enumerate(raw_reqs):
            requirements.append({
                "id": r.get("id") or f"req_{str(idx+1).zfill(3)}",
                "text": (r.get("text") or r.get("requirement") or r.get("description") or "").strip(),
                "category": r.get("category") or "other",
                "priority": r.get("priority") or "unknown",
                "is_hard_requirement": bool(r.get("is_hard_requirement", False)),
                "keywords": r.get("keywords") or [],
                "reason": r.get("reason") or ""
            })
            
    if not requirements:
        requirements = [
            {
                "id": "req_001",
                "text": jd_text[:300].strip() + "...",
                "category": "other",
                "priority": "must_have",
                "is_hard_requirement": False,
                "keywords": [],
                "reason": "JD 结构化提取未识别到要求，降级为全文模糊匹配"
            }
        ]
        
    result = {
        "job_title": parsed.get("job_title") or "未知岗位",
        "company": parsed.get("company") or "未知公司",
        "location": parsed.get("location") or "未注明地点",
        "employment_type": parsed.get("employment_type") or "unknown",
        "work_mode": parsed.get("work_mode") or "unknown",
        "requirements": requirements,
        "responsibilities": parsed.get("responsibilities") or [],
        "hard_constraints": [
            {
                "type": hc.get("type") or "other",
                "text": hc.get("text") or "",
                "blocking_level": hc.get("blocking_level") or "unknown"
            } for hc in (parsed.get("hard_constraints") or []) if isinstance(hc, dict)
        ],
        "nice_to_have": parsed.get("nice_to_have") or [],
        "raw_text": jd_text
    }
    _JD_PARSE_CACHE[cache_key] = result
    _limit_cache_size(_JD_PARSE_CACHE)
    return result

def check_hard_constraints_py(client: Any, model: str, parsed_jd: dict, parsed_resume: dict) -> dict:
    hard_constraints = parsed_jd.get("hard_constraints") or []
    if not hard_constraints:
        return {
            "hard_risks": [],
            "has_blocking_risk": False
        }
        
    jd_raw = parsed_jd.get("raw_text") or ""
    jd_hash = hashlib.md5(jd_raw.encode("utf-8")).hexdigest()
    resume_cleaned = parsed_resume.get("cleanedText") or ""
    resume_hash = hashlib.md5(resume_cleaned.encode("utf-8")).hexdigest()
    cache_key = f"{jd_hash}:{resume_hash}:{model}"
    if cache_key in _HARD_CONSTRAINTS_CACHE:
        print(f"[BG_ANALYSIS] check_hard_constraints_py cache hit for key: {cache_key}")
        return _HARD_CONSTRAINTS_CACHE[cache_key]

    prompt = f"""
You are an objective recruitment screening auditor. Your task is to audit the candidate's resume against the hard constraints specified in the Job Description.

Hard Constraints to check:
{json.dumps(hard_constraints, ensure_ascii=False, indent=2)}

Candidate Profile Summary:
{json.dumps(parsed_resume.get("extractedProfile") or {}, ensure_ascii=False, indent=2)}

Candidate Raw Resume Text:
{parsed_resume.get("cleanedText", "")}

Instructions:
- Carefully evaluate if the candidate satisfies each hard constraint.
- Status must be "pass" (clearly meets), "fail" (clearly does not meet), or "unknown" (information not present in resume).
- Do not guess! If there is no mention of visa, student graduation date, or specific location availability, mark status as "unknown" and request verification in the reason.
- A severity of "blocking" means the failure is a complete showstopper (e.g., student status for an internship when already graduated, or completely missing degree level requirements).
- Output valid JSON only matching the schema.
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        content = response.choices[0].message.content
        parsed = json.loads(_strip_json_fence(content))
    except Exception as e:
        print(f"[BG_ANALYSIS] checkHardConstraints failed: {e}")
        parsed = {}
        
    risks = []
    for r in (parsed.get("hard_risks") or []):
        if isinstance(r, dict):
            risks.append({
                "constraint": r.get("constraint") or "",
                "type": r.get("type") or "other",
                "status": r.get("status") or "unknown",
                "severity": r.get("severity") or "minor",
                "reason": r.get("reason") or "",
                "evidence": r.get("evidence") or []
            })
            
    result = {
        "hard_risks": risks,
        "has_blocking_risk": bool(parsed.get("has_blocking_risk", False))
    }
    _HARD_CONSTRAINTS_CACHE[cache_key] = result
    _limit_cache_size(_HARD_CONSTRAINTS_CACHE)
    return result

def run_background_resume_analysis(
    user_id: Any,
    record_id: str,
    draft_data: dict,
    resume_file_id: str,
    embedding_config_id: Optional[str] = None,
    chat_config_id: Optional[str] = None
) -> None:
    try:
        # Step 1: Validate input
        update_background_progress(user_id, record_id, "validate", "running")
        
        # Verify inputs exist
        jd_text = draft_data.get("jdText", "").strip()
        if not jd_text or len(jd_text) < 80:
            raise ValueError("岗位 JD 内容过短，请检查输入后重新提交分析。")
            
        parsed_resume = db.get_user_resume(user_id, resume_file_id)
        if not parsed_resume:
            raise ValueError("未找到已解析的简历文件。")
            
        chunks = parsed_resume.get("chunks") or []
        if not chunks:
            raise ValueError("简历解析结果为空，没有有效的简历文本片段。")
            
        # Resolve LLM configuration
        chat_client, resolved_chat_config_id, chat_provider, chat_model = analyzer._client(user_id, chat_config_id)
        
        # Resolve Embedding configuration
        emb_provider, emb_model, _, _ = service._resolve_embedding_config(user_id)
        
        # Validate complete success
        update_background_progress(user_id, record_id, "validate", "success")
        
        # Step 2: Vectorize resume chunks
        update_background_progress(user_id, record_id, "resume_embedding", "running", {
            "embeddedChunksCount": 0,
            "chunksCount": len(chunks)
        })
        
        embedded_chunks = []
        for idx, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            # service.get_embedding_for_text automatically hashes and caches to the DB table `embeddings`
            embedding = service.get_embedding_for_text(user_id, content) or []
            embedded_chunks.append({
                **chunk,
                "embedding": embedding
            })
            update_background_progress(user_id, record_id, "resume_embedding", "running", {
                "embeddedChunksCount": idx + 1,
                "chunksCount": len(chunks)
            })
            
        update_background_progress(user_id, record_id, "resume_embedding", "success")
        
        # Step 3: Vectorize job JD
        update_background_progress(user_id, record_id, "jd_embedding", "running")
        
        # Stage A: Structural decomposition using LLM
        parsed_jd = parse_job_description_py(chat_client, chat_model, jd_text)
        
        # Stage B: Vectorize whole JD
        jd_embedding = service.get_embedding_for_text(user_id, jd_text) or []
        update_background_progress(user_id, record_id, "jd_embedding", "success")
        
        # Step 4: Retrieve most relevant chunks
        update_background_progress(user_id, record_id, "retrieve_chunks", "running")
        
        requirement_matches = []
        for req in parsed_jd["requirements"]:
            req_text = req["text"]
            req_embedding = service.get_embedding_for_text(user_id, req_text) or []
            
            matched_evidence = []
            if req_embedding:
                scored = []
                for ec in embedded_chunks:
                    sim = cosine_similarity_py(req_embedding, ec.get("embedding") or [])
                    scored.append({"chunk": ec, "similarity": sim})
                # Sort descending
                scored.sort(key=lambda x: x["similarity"], reverse=True)
                
                # Take top K (3) with threshold check
                for item in scored[:3]:
                    matched_evidence.append({
                        "evidence_id": item["chunk"]["id"],
                        "evidence_text": item["chunk"]["content"],
                        "evidence_type": item["chunk"].get("section") or "other",
                        "similarity": round(float(item["similarity"]), 4),
                        "source_section": item["chunk"].get("section") or "other"
                    })
                    
            best_sim = max([e["similarity"] for e in matched_evidence]) if matched_evidence else 0.0
            
            requirement_matches.append({
                "requirement_id": req["id"],
                "requirement_text": req["text"],
                "priority": req["priority"],
                "is_hard_requirement": req["is_hard_requirement"],
                "matched_evidence": matched_evidence,
                "best_similarity": best_sim,
                "has_potential_evidence": best_sim >= 0.3
            })
            
        retrieved_chunks = []
        seen_ids = set()
        for rm in requirement_matches:
            for ev in rm["matched_evidence"]:
                c_id = ev["evidence_id"]
                if c_id not in seen_ids:
                    seen_ids.add(c_id)
                    orig = next((c for c in embedded_chunks if c["id"] == c_id), None)
                    if orig:
                        retrieved_chunks.append({
                            **orig,
                            "score": round(ev["similarity"] * 100),
                            "embedding": None
                        })
        retrieved_chunks.sort(key=lambda x: x.get("score") or 0, reverse=True)
        
        # Fallback if no matching chunks retrieved
        if not retrieved_chunks and jd_embedding:
            scored = []
            for ec in embedded_chunks:
                sim = cosine_similarity_py(jd_embedding, ec.get("embedding") or [])
                scored.append({
                    **ec,
                    "score": round(sim * 100),
                    "embedding": None
                })
            scored.sort(key=lambda x: x.get("score") or 0, reverse=True)
            retrieved_chunks = scored[:8]
            
        update_background_progress(user_id, record_id, "retrieve_chunks", "success", {
            "retrievedChunksCount": len(retrieved_chunks)
        })
        
        if not retrieved_chunks:
            raise ValueError("没有检索到相关简历片段，请检查简历解析结果或 JD 内容。")
            
        # Step 5: Call Gemini analysis
        update_background_progress(user_id, record_id, "gemini_analysis", "running", {
            "subState": "checking_constraints",
            "subProgress": 15
        })
        
        # Stage A: Check hard constraints
        hard_constraints_res = check_hard_constraints_py(chat_client, chat_model, parsed_jd, parsed_resume)
        
        # Check deep analysis cache
        jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
        resume_hash = hashlib.md5(parsed_resume.get("cleanedText", "").encode("utf-8")).hexdigest()
        material = draft_data.get("candidateMaterial") or "无"
        material_hash = hashlib.md5(material.encode("utf-8")).hexdigest()
        deep_cache_key = f"{jd_hash}:{resume_hash}:{material_hash}:{chat_model}"
        
        parsed_analysis = None
        if deep_cache_key in _DEEP_ANALYSIS_CACHE:
            print(f"[BG_ANALYSIS] Deep analysis cache hit for key: {deep_cache_key}")
            parsed_analysis = _DEEP_ANALYSIS_CACHE[deep_cache_key]
        else:
            # Stage B: Structured deep LLM analysis prompt
            update_background_progress(user_id, record_id, "gemini_analysis", "running", {
                "subState": "deep_analyzing",
                "subProgress": 50
            })
            
            prompt = f"""你是一名严格、客观、不讨好用户的求职分析专家。
你必须基于提供的 JD 结构化结果、简历证据片段、向量召回结果 and 硬性条件检查结果进行分析。
向量相似度只代表语义相关，不代表用户满足岗位要求。
你不能编造用户没有提供的经历。
你不能把“学习过”当成“熟练掌握”。
你不能把课程项目直接等同于生产经验。
你必须区分 matched、partial、missing、unknown。
如果证据不足，必须输出 unknown 或 evidence_insufficient。
如果存在硬性风险，必须优先指出。
请输出严格 JSON，不要输出 markdown，不要包含 markdown 代码块。

【分析输入】
1. 岗位结构化 JD:
{json.dumps(parsed_jd, ensure_ascii=False, indent=2)}

2. 针对每个岗位要求的简历向量召回证据 (requirementMatches):
{json.dumps(requirement_matches, ensure_ascii=False, indent=2)}

3. 硬性条件筛查结果 (hardConstraintsResult):
{json.dumps(hard_constraints_res, ensure_ascii=False, indent=2)}

4. 候选人补充说明:
{draft_data.get("candidateMaterial") or "无"}

【输出 JSON 格式要求】
必须严格符合以下 JSON 模式 (JSON Schema)：
{{
  "requirement_assessments": [
    {{
      "requirement_id": "req_001",
      "requirement_text": "JD要求原文",
      "status": "matched | partial | missing | unknown",
      "confidence": "high | medium | low",
      "evidence_used": ["关联的简历片段 ID，如 chunk id"],
      "reason": "具体匹配判断理由，基于证据对比",
      "gap": "逻辑缺陷或不匹配之处",
      "fixable_by_resume_rewrite": true
    }}
  ],
  "decision": {{
    "decision": "strong_apply | apply | apply_after_revision | low_priority | not_recommended",
    "confidence": "high | medium | low",
    "overall_score": 85,
    "summary": "一句话投递决策总结",
    "why_this_decision": ["决策理由 1", "决策理由 2"],
    "main_risks": ["潜在缺口或硬性条件风险 1", "潜在缺口 2"],
    "main_opportunities": ["已具备优势或机会 1", "机会 2"]
  }},
  "matchBreakdown": {{
    "techStack": 90,
    "projectExperience": 80,
    "educationBackground": 85,
    "keywordCoverage": 75,
    "seniorityFit": 80,
    "competitionLevel": 70,
    "evidenceStrength": 80,
    "resumeImprovementPotential": 85
  }},
  "resume_rewrite_suggestions": [
    {{
      "target_requirement_id": "req_001",
      "resume_section": "项目经历/工作经历/技能",
      "current_problem": "当前简历表达的问题",
      "rewrite_strategy": "改写策略与方向",
      "example_rewrite": "改写后的高契合度对比表达，符合 STAR 原则和量化要求，不虚构经历",
      "risk": "do_not_exaggerate | needs_more_evidence | safe_to_rewrite"
    }}
  ],
  "learning_plan": [
    {{
      "gap": "对应缺失的技能或业务背景",
      "topic": "推荐学习或刷题的主题",
      "priority": "high | medium | low",
      "reason": "推荐理由，与岗位的关联性",
      "suggested_action": "具体的学习/刷题行动指南",
      "estimated_effort": "2天 / 5天 / 2周"
    }}
  ],
  "interview_prep": [
    {{
      "topic": "常问高频技术点",
      "question_type": "技术问答 / 场景设计 / 取舍分析",
      "reason": "JD 强相关且简历中仅偏理论"
    }}
  ]
}}
"""
            try:
                response = chat_client.chat.completions.create(
                    model=chat_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                llm_text = response.choices[0].message.content
                parsed_analysis = json.loads(_strip_json_fence(llm_text))
            except Exception as chat_err:
                print(f"[BG_ANALYSIS] Chat completion with JSON mode failed: {chat_err}, trying standard completion")
                response = chat_client.chat.completions.create(
                    model=chat_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                llm_text = response.choices[0].message.content
                parsed_analysis = json.loads(_strip_json_fence(llm_text))
                
            _DEEP_ANALYSIS_CACHE[deep_cache_key] = parsed_analysis
            _limit_cache_size(_DEEP_ANALYSIS_CACHE)
            
        update_background_progress(user_id, record_id, "gemini_analysis", "success")
        
        # Step 6: Save history record
        update_background_progress(user_id, record_id, "save_history", "running")
        
        # --- Post-process and normalize results ---
        raw_decision = parsed_analysis.get("decision", {}) or {}
        raw_breakdown = parsed_analysis.get("matchBreakdown", {}) or {}
        
        # Calculated unified score
        tech_stack = int(raw_breakdown.get("techStack", 50))
        project_experience = int(raw_breakdown.get("projectExperience", 50))
        education_background = int(raw_breakdown.get("educationBackground", 50))
        keyword_coverage = int(raw_breakdown.get("keywordCoverage", 50))
        
        calculated_score = round(
            education_background * 0.3 +
            tech_stack * 0.3 +
            project_experience * 0.3 +
            keyword_coverage * 0.1
        )
        
        # Enforce Scheme 1: Education <= 40 caps match score at 59
        if education_background <= 40:
            calculated_score = min(59, calculated_score)
            
        # Hard constraint blocking risk caps match score at 50
        overall_decision = raw_decision.get("decision") or "cautious"
        if hard_constraints_res.get("has_blocking_risk"):
            calculated_score = min(calculated_score, 50)
            if overall_decision in ("strong_apply", "apply"):
                overall_decision = "cautious"
                
        # Map decision labels
        final_decision = "maybe"
        if overall_decision in ("strong_apply", "strong_yes"):
            final_decision = "strong_yes"
        elif overall_decision in ("apply", "yes"):
            final_decision = "yes"
        elif overall_decision in ("cautious", "maybe", "apply_after_revision"):
            final_decision = "maybe"
        elif overall_decision in ("not_recommended", "no", "low_priority"):
            final_decision = "no"
            
        # Map dimension descriptions
        def dimension_obj(dim_id, label, score, explanation):
            return {
                "id": dim_id,
                "label": label,
                "score": max(0, min(100, int(score))),
                "tags": [],
                "explanation": explanation
            }
            
        dimensions = [
            dimension_obj("techStack", "技能匹配", tech_stack, "基于 JD 技术栈和检索片段的技术证据判断。"),
            dimension_obj("projectExperience", "项目经历匹配", project_experience, "基于项目深度、职责边界和交付结果判断。"),
            dimension_obj("educationBackground", "学历 / 背景匹配", education_background, "基于教育背景和岗位门槛判断。"),
            dimension_obj("keywordCoverage", "关键词覆盖", keyword_coverage, "基于 JD 关键词在检索片段中的覆盖判断。"),
            dimension_obj("seniorityFit", "年限 / 级别匹配", raw_breakdown.get("seniorityFit", 50), "基于岗位级别和简历证据判断。"),
            dimension_obj("competitionLevel", "岗位竞争难度", raw_breakdown.get("competitionLevel", 50), "竞争难度越高，越需要强证据支撑。"),
            dimension_obj("evidenceStrength", "证据强度", raw_breakdown.get("evidenceStrength", 50), "检索片段是否足以支撑投递判断。"),
            dimension_obj("resumeImprovementPotential", "简历改造空间", raw_breakdown.get("resumeImprovementPotential", 50), "通过改写和补证据能提升多少匹配度。")
        ]
        
        # Map rewrite recommendations
        advice_list = []
        raw_advice = parsed_analysis.get("resume_rewrite_suggestions") or []
        if isinstance(raw_advice, list):
            for idx, s in enumerate(raw_advice):
                based_chunk_ids = []
                req_id = s.get("target_requirement_id")
                if req_id and isinstance(parsed_analysis.get("requirement_assessments"), list):
                    ass = next((a for a in parsed_analysis["requirement_assessments"] if a.get("requirement_id") == req_id), None)
                    if ass and isinstance(ass.get("evidence_used"), list):
                        based_chunk_ids = [str(cid) for cid in ass["evidence_used"] if cid]
                        
                req_priority = "unknown"
                if req_id and requirement_matches:
                    rm = next((m for m in requirement_matches if m.get("requirement_id") == req_id), None)
                    if rm:
                        req_priority = rm.get("priority")
                        
                risk = s.get("risk") or "safe_to_rewrite"
                priority = "low"
                if risk == "needs_more_evidence":
                    priority = "high"
                elif risk == "safe_to_rewrite":
                    priority = "high" if req_priority == "must_have" else "medium"
                else:
                    priority = "medium" if req_priority == "must_have" else "low"
                    
                advice_list.append({
                    "id": f"advice-{idx}",
                    "priority": priority,
                    "issue": f"【{s.get('resume_section') or '简历表达'}】针对岗位要求 ID \"{req_id or '未知要求'}\" 的不足之处：{s.get('current_problem')}",
                    "suggestion": s.get("rewrite_strategy") or "",
                    "example": s.get("example_rewrite") or "",
                    "impact": "需补充强力真实经历/证书证据，避免虚构" if priority == "high" else "安全改写表述，大幅提升简历契合度" if priority == "medium" else "细节微调润色，提供更丰富的量化支撑",
                    "basedOnChunkIds": based_chunk_ids,
                    "target_requirement_id": req_id,
                    "resume_section": s.get("resume_section"),
                    "risk": risk
                })
                
        # Map learning plan
        suggestions = []
        raw_learning = parsed_analysis.get("learning_plan") or []
        if isinstance(raw_learning, list):
            for idx, l in enumerate(raw_learning):
                suggestions.append({
                    "id": f"learning-{idx}",
                    "skill": l.get("topic") or l.get("gap") or "专业背景提升",
                    "order": idx + 1,
                    "estimatedTime": l.get("estimated_effort") or "3-7 天",
                    "practiceDirection": f"【缺口: {l.get('gap')}】行动指南: {l.get('suggested_action')}",
                    "interviewFocus": f"【重点】{l.get('reason')}",
                    "gap": l.get("gap"),
                    "priority": l.get("priority"),
                    "reason": l.get("reason")
                })
                
        # Citations
        cited_chunks = []
        if isinstance(parsed_analysis.get("requirement_assessments"), list):
            ids = set()
            for ass in parsed_analysis["requirement_assessments"]:
                if isinstance(ass.get("evidence_used"), list):
                    for cid in ass["evidence_used"]:
                        if cid:
                            ids.add(str(cid))
            cited_chunks = list(ids)
            
        # Next actions
        next_actions = [
            "针对硬性条件和筛查结论进行自查与核实",
            "优先改造【必须改 (高优先级)】的简历表达",
            "围绕岗位核心缺口做针对性的项目实践和学习",
            "准备面试中的取舍论证和场景设计"
        ]
        raw_prep = parsed_analysis.get("interview_prep") or []
        if isinstance(raw_prep, list):
            for prep in raw_prep[:2]:
                next_actions.append(f"准备面试问题：{prep.get('topic')} (类型: {prep.get('question_type')}，原因: {prep.get('reason')})")
                
        # Construct final AnalysisResult payload
        average_score = 0
        if retrieved_chunks:
            average_score = round(sum(c.get("score") or 0 for c in retrieved_chunks) / len(retrieved_chunks))
            
        final_result = {
            "id": record_id,
            "createdAt": datetime_now_str(),
            "draft": draft_data,
            "sourceDraftId": record_id,
            "resumeFile": {
                "id": resume_file_id,
                "name": parsed_resume.get("file", {}).get("name") or "resume.pdf",
                "size": parsed_resume.get("file", {}).get("size") or 0,
                "type": parsed_resume.get("file", {}).get("type") or "application/pdf",
                "uploadedAt": parsed_resume.get("file", {}).get("uploadedAt") or datetime_now_str(),
                "status": "indexed"
            },
            "parsedResume": {
                "file": parsed_resume.get("file") or {},
                "cleanedText": parsed_resume.get("cleanedText") or "",
                "extractedProfile": parsed_resume.get("extractedProfile") or {},
                "chunks": [{**c, "embedding": None} for c in chunks]
            },
            "retrievedResumeChunks": retrieved_chunks,
            "retrievalSummary": f"使用 {emb_provider} / {emb_model} 召回 {len(retrieved_chunks)} 个简历片段。",
            "retrievalScore": average_score,
            "modelUsage": {
                "embeddingProvider": emb_provider,
                "embeddingModelId": emb_model,
                "chatProvider": chat_provider,
                "chatModelId": chat_model,
                "retrievalTopK": 8,
                "createdAt": datetime_now_str()
            },
            "citedResumeChunks": cited_chunks,
            "decision": final_decision,
            "matchScore": max(0, min(100, calculated_score)),
            "riskLevel": "low" if calculated_score >= 75 else "medium" if calculated_score >= 50 else "high",
            "priority": "P0" if calculated_score >= 85 else "P1" if calculated_score >= 70 else "P2" if calculated_score >= 50 else "P3",
            "oneLineReason": raw_decision.get("summary") or "分析已完成。",
            "detectedKeywords": raw_decision.get("main_opportunities") or [],
            "missingKeywords": raw_decision.get("main_risks") or [],
            "dimensions": dimensions,
            "resumeAdvice": advice_list,
            "learningSuggestions": suggestions,
            "nextActions": next_actions,
            
            # Pipeline parameters
            "parsedJD": parsed_jd,
            "requirementMatches": { "requirement_matches": requirement_matches },
            "hardConstraintsResult": hard_constraints_res,
            "requirementAssessments": parsed_analysis.get("requirement_assessments") or []
        }
        
        # Complete last step
        final_result["steps"] = [
            { "id": "validate", "title": "检查输入与配置", "description": "正在验证输入内容并加载模型配置...", "status": "success" },
            { "id": "resume_embedding", "title": "向量化简历片段", "description": "正在生成简历片段的向量索引...", "status": "success", "metadata": { "embeddedChunksCount": len(chunks), "chunksCount": len(chunks) } },
            { "id": "jd_embedding", "title": "向量化岗位 JD", "description": "正在对岗位描述进行结构化分析与向量化...", "status": "success" },
            { "id": "retrieve_chunks", "title": "检索最相关片段", "description": "基于语义相似度检索最匹配的简历经历...", "status": "success", "metadata": { "retrievedChunksCount": len(retrieved_chunks) } },
            { "id": "gemini_analysis", "title": "调用 Gemini 分析", "description": "大语言模型正在进行匹配度深度审计与改写建议...", "status": "success" },
            { "id": "save_history", "title": "保存分析记录", "description": "保存分析数据至云端面板...", "status": "success" }
        ]
        final_result["progressStep"] = -1
        
        # Decrement limit for standard users after successful background analysis
        user = db.get_user_by_id(user_id)
        if user and user.role != "admin":
            db.decrement_user_generation_limit(user_id)
            
        # Save final complete record in 'watching' status
        db.save_analysis_record(
            user_id=user_id,
            status="watching",
            result_json=final_result,
            input_json=final_result.get("draft"),
            record_id=record_id
        )
        print(f"[BG_ANALYSIS] Background task {record_id} completed successfully.")
        
    except Exception as exc:
        print(f"[BG_ANALYSIS] Background task {record_id} failed: {exc}")
        import traceback
        traceback.print_exc()
        
        # Save a failed record
        failed_result = {
            "id": record_id,
            "createdAt": datetime_now_str(),
            "draft": draft_data,
            "sourceDraftId": record_id,
            "resumeFile": None,
            "parsedResume": None,
            "retrievedResumeChunks": [],
            "retrievalSummary": f"分析中断。原因: {exc}",
            "retrievalScore": 0,
            "decision": "no",
            "matchScore": 0,
            "riskLevel": "high",
            "priority": "P3",
            "oneLineReason": f"分析失败: {exc}",
            "detectedKeywords": [],
            "missingKeywords": [],
            "dimensions": [],
            "resumeAdvice": [],
            "learningSuggestions": [],
            "nextActions": ["检查模型配置或网络连接", "点击重新分析以重试"],
            "citedResumeChunks": [],
            "is_failed": True,
            "errorMessage": str(exc)
        }
        
        # Update progress steps to failed
        record = db.get_analysis_record(user_id, record_id) or {}
        steps = record.get("steps") or []
        for step in steps:
            if step["status"] == "running":
                step["status"] = "failed"
                step["errorMessage"] = str(exc)
                break
        failed_result["steps"] = steps
        failed_result["progressStep"] = record.get("progressStep", -1)
        
        db.save_analysis_record(
            user_id=user_id,
            status="failed",
            result_json=failed_result,
            input_json=draft_data,
            record_id=record_id
        )

def datetime_now_str() -> str:
    from datetime import datetime
    return datetime.now().isoformat()

# Simple global session cache for tailored fields
_TAILOR_CACHE = {}

def tailor_form_fields_py(
    user_id: Any,
    resume_file_id: str,
    jd_text: str,
    fields: list[str],
    chat_config_id: Optional[str] = None
) -> dict:
    import re
    parsed_resume = db.get_user_resume(user_id, resume_file_id)
    if not parsed_resume:
        raise ValueError("未找到已解析的简历文件。")

    profile_summary = parsed_resume.get("extractedProfile", {})

    settings = db.get_settings(user_id) or {}
    preset_profile = settings.get("profile") or {}

    # Extract personal profile details early (manually configured education overrides)
    edu = preset_profile.get("education") or profile_summary.get("education") or {}
    if isinstance(edu, list) and len(edu) > 0:
        edu = edu[0]
        
    school_val = ""
    major_val = ""
    degree_val = ""
    grad_year_val = ""

    if isinstance(edu, dict):
        school_val = edu.get("school") or edu.get("学校") or ""
        major_val = edu.get("major") or edu.get("专业") or ""
        degree_val = edu.get("degree") or edu.get("学历") or ""
        grad_year_val = edu.get("graduation_year") or edu.get("grad_year") or edu.get("毕业年份") or edu.get("毕业时间") or ""
    elif isinstance(edu, str):
        school_val = edu
        school_match = re.search(r"\S*(?:大学|学院|分校)\S*", edu)
        if school_match:
            school_val = school_match.group(0)
            
        degree_match = re.search(r"本科|学士|硕士|研究生|博士|大专|高中", edu)
        if degree_match:
            degree_val = degree_match.group(0)
            
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", edu)
        if year_match:
            grad_year_val = year_match.group(1)
            
        parts = edu.split()
        major_parts = []
        for p in parts:
            if school_val and p in school_val:
                continue
            if degree_val and p in degree_val:
                continue
            if grad_year_val and p in grad_year_val:
                continue
            if any(char.isdigit() or char in "-—" for char in p):
                continue
            major_parts.append(p)
        if major_parts:
            major_val = " ".join(major_parts)

    profile = {
        "name": preset_profile.get("name") or profile_summary.get("name") or profile_summary.get("姓名") or "",
        "phone": preset_profile.get("phone") or profile_summary.get("phone") or profile_summary.get("mobile") or profile_summary.get("电话") or profile_summary.get("手机号") or "",
        "email": preset_profile.get("email") or profile_summary.get("email") or profile_summary.get("邮箱") or "",
        "school": school_val or preset_profile.get("school") or profile_summary.get("school") or profile_summary.get("学校") or "",
        "major": major_val or preset_profile.get("major") or profile_summary.get("major") or profile_summary.get("专业") or "",
        "degree": degree_val or preset_profile.get("degree") or profile_summary.get("degree") or profile_summary.get("学历") or "",
        "grad_year": grad_year_val or preset_profile.get("grad_year") or profile_summary.get("graduation_year") or profile_summary.get("毕业年份") or profile_summary.get("毕业时间") or "",
        "gender": preset_profile.get("gender") or "",
        "birth_date": preset_profile.get("birthDate") or "",
        "political_status": preset_profile.get("politicalStatus") or "",
        "hometown": preset_profile.get("hometown") or "",
        "expected_salary": preset_profile.get("expectedSalary") or "",
        "wechat": preset_profile.get("wechat") or "",
        "gpa": preset_profile.get("gpa") or ""
    }

    # Optimization 1: Bypass LLM completely if no AI tailored fields are requested
    if not fields:
        return {
            "tailored_data": {},
            "profile": profile
        }

    import hashlib
    # Compute MD5 of inputs to check memory cache
    jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()
    fields_key = ",".join(sorted(fields))
    cache_key = f"{resume_file_id}:{jd_hash}:{fields_key}:{chat_config_id}"

    # Optimization 2: Cache hit check
    if cache_key in _TAILOR_CACHE:
        print(f"[TAILOR_FIELDS] Cache hit for key {cache_key}")
        return {
            "tailored_data": _TAILOR_CACHE[cache_key],
            "profile": profile
        }

    chat_client, _, _, chat_model = analyzer._client(user_id, chat_config_id)
    resume_text = parsed_resume.get("cleanedText", "")

    fields_desc = []
    for f in fields:
        if f == "self_evaluation":
            fields_desc.append("- self_evaluation: 针对岗位JD定制的自我评价（不超过300字），突出候选人与岗位的核心匹配点。")
        elif f == "projects":
            fields_desc.append("- projects: 从简历中提炼出最匹配该岗位的项目经历（STAR原则：背景、任务、行动、结果），以量化结果优先，针对岗位职责进行改写，不虚构经历。")
        elif f == "work_experience":
            fields_desc.append("- work_experience: 针对岗位的实习/工作经历描述，强调在过去的工作中承担的与当前岗位相关的职责和业绩。")
        elif f == "skills":
            fields_desc.append("- skills: 匹配JD所需的技能清单，根据简历提及的技能分类整理（如：熟练掌握、了解等），优先排序最吻合的技能。")
        elif f == "advantages":
            fields_desc.append("- advantages: 个人优势/亮点总结，突出符合岗位痛点解决能力、技术特长或学习能力。")
        else:
            fields_desc.append(f"- {f}: 根据当前岗位 JD 精心改写并提炼简历中与之相关的部分。")

    fields_list_str = "\n".join(fields_desc)

    # Optimization 3: Compressed concise prompt
    prompt = f"""你是一个网申简历文案定制助手。请基于候选人简历和投递岗位描述（JD），针对指定的字段进行提炼与改写。

要求：
- 严格基于简历真实经历与数据，不可捏造。
- 提炼出与岗位JD最相关的技能或项目，量化结果优先，格式裁剪以适应字段。
- 请直接输出 JSON，格式为：{{ "字段名": "改写提炼后的文案内容" }}。

【输入数据】
1. 岗位 JD:
{jd_text}

2. 简历概要:
{json.dumps(profile_summary, ensure_ascii=False, indent=2)}

3. 简历全文:
{resume_text}

【需要生成的字段规范】
{fields_list_str}

只返回合法 JSON，不包含 markdown 格式或代码块包裹。
"""
    try:
        response = chat_client.chat.completions.create(
            model=chat_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        content = response.choices[0].message.content
        result = json.loads(_strip_json_fence(content))
    except Exception as e:
        print(f"[TAILOR_FIELDS] AI tailoring failed: {e}, retrying standard mode")
        try:
            response = chat_client.chat.completions.create(
                model=chat_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            content = response.choices[0].message.content
            result = json.loads(_strip_json_fence(content))
        except Exception as e2:
            print(f"[TAILOR_FIELDS] AI tailoring completely failed: {e2}")
            result = {f: "智能提炼失败，请手动填写" for f in fields}

    # Save to cache
    _TAILOR_CACHE[cache_key] = result

    return {
        "tailored_data": result,
        "profile": profile
    }
