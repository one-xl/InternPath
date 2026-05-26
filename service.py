from datetime import datetime
from typing import Any, List, Literal, Optional, Tuple, Union
from uuid import uuid4

from ai_service_client import AiServiceClient
from ai_analyzer import AIAnalyzer
from crawler_api import BilibiliAPICrawlerSync
from database import Database
from document_parser import extract_text_from_uploaded_file
from models import (
    BilibiliCourse,
    ExamOptionsForPractice,
    FitExamAttempt,
    FitExamPaper,
    JDRecord,
    JobAnalysis,
    JobPosting,
    PersonalDecision,
    SalarySnapshot,
    SalaryTrendPrediction,
    StarStory,
)
from practice_app import PracticeAppInvoker
from ranker import CourseRanker
from salary_scraper import linear_next_forecast_k, scrape_salary_from_url


KNOWLEDGE_CHUNK_SIZE = 700
KNOWLEDGE_CHUNK_OVERLAP = 100


def chunk_text_light(text: str, chunk_size: int = KNOWLEDGE_CHUNK_SIZE, overlap: int = KNOWLEDGE_CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: List[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks


def build_knowledge_chunks(
    raw_text: str,
    *,
    document_id: int,
    source_type: str,
    file_name: str,
) -> List[dict]:
    chunks = []
    for index, text in enumerate(chunk_text_light(raw_text)):
        chunks.append(
            {
                "chunkIndex": index,
                "text": text,
                "tokenCount": len(text),
                "metadata": {
                    "documentId": str(document_id),
                    "sourceType": source_type,
                    "fileName": file_name,
                    "chunkIndex": index,
                },
            }
        )
    return chunks


class CareerPathAIService:
    def __init__(self):
        self.ai_analyzer = AIAnalyzer()
        self.crawler = BilibiliAPICrawlerSync()
        self.ranker = CourseRanker()
        self.db = Database()
        self.practice_invoker = PracticeAppInvoker()
        self.ai_service_client = AiServiceClient()

    def user_db(self, user_id: int) -> Database:
        return Database.for_user(user_id)

    def extract_skills(self, jd_text: str) -> JobAnalysis:
        return self.ai_analyzer.extract_skills(jd_text)

    def build_personal_decision(
        self,
        *,
        jd_text: str,
        analysis: JobAnalysis,
        resume_text: str = "",
        knowledge_texts: Optional[List[str]] = None,
    ) -> PersonalDecision:
        try:
            return self.ai_analyzer.generate_personal_decision(
                jd_text=jd_text,
                analysis=analysis,
                resume_text=resume_text,
                knowledge_texts=knowledge_texts or [],
            )
        except Exception:
            return self._fallback_personal_decision(
                analysis=analysis,
                resume_text=resume_text,
                knowledge_texts=knowledge_texts or [],
            )

    def _fallback_personal_decision(
        self,
        *,
        analysis: JobAnalysis,
        resume_text: str,
        knowledge_texts: List[str],
    ) -> PersonalDecision:
        material_text = "\n".join([resume_text, *knowledge_texts]).lower()
        skills = analysis.skills or []
        matched = [skill for skill in skills if skill.lower() in material_text]
        missing = [skill for skill in skills if skill not in matched]
        ratio = len(matched) / len(skills) if skills else 0.0
        score = int(round(35 + ratio * 55)) if skills else 45
        if ratio >= 0.7:
            recommendation = "APPLY"
        elif ratio >= 0.35:
            recommendation = "CONSIDER"
        else:
            recommendation = "SKIP"

        return PersonalDecision(
            recommendation=recommendation,
            match_score=max(0, min(100, score)),
            decision_reasons=[
                f"JD 难度为 {analysis.difficulty}，核心要求集中在 {', '.join(skills[:4]) or '岗位能力'}。",
                f"当前材料能直接覆盖 {len(matched)} 个核心技能。",
                "该判断来自本地兜底规则，建议补充更完整的简历或项目材料后重新分析。",
            ],
            critical_gaps=[f"缺少 {skill} 的明确项目或经历证据" for skill in missing[:5]],
            resume_rewrites=[
                f"围绕 {skill} 补写一条项目经历：说明场景、动作、技术栈和量化结果。"
                for skill in matched[:5]
            ] or ["先补充一段最能代表你能力的项目经历，再重新生成简历改造建议。"],
            evidence_needed=[f"补充能证明 {skill} 的项目、课程作业或实习片段" for skill in missing[:5]],
            action_plan=[
                "先把 JD 中最核心的 3 个技能映射到自己的项目经历。",
                "把简历中泛泛的职责描述改成可验证的结果描述。",
                "对缺口技能补一个小项目或刷题记录，再决定是否投递。",
            ],
            learning_plan=[f"优先补齐 {skill} 的基础和一个可展示练习" for skill in missing[:5]],
        )

    def analyze_jd_with_guardrails(
        self,
        *,
        user_id: int,
        jd_text: str,
        resume_text: str = "",
        knowledge_texts: Optional[List[str]] = None,
        options: Optional[dict[str, bool]] = None,
        original_analysis: Optional[JobAnalysis] = None,
        jd_id: Optional[int] = None,
        selected_document_ids: Optional[List[int]] = None,
    ) -> dict[str, Any]:
        task_id = f"internpath-{uuid4().hex}"
        active_options = {
            "enableRag": True,
            "enableVerification": True,
            "enableHallucinationCheck": True,
            "enableRewrite": True,
            **(options or {}),
        }
        db = self.user_db(user_id)
        db.create_analysis_task(
            user_id=user_id,
            task_id=task_id,
            jd_id=jd_id,
            enable_rag=bool(active_options.get("enableRag")),
            enable_verification=bool(active_options.get("enableVerification")),
            enable_hallucination_check=bool(active_options.get("enableHallucinationCheck")),
            enable_rewrite=bool(active_options.get("enableRewrite")),
        )
        db.update_analysis_task_status(user_id, task_id, "PROCESSING")

        try:
            analysis = original_analysis or self.extract_skills(jd_text)
        except Exception as exc:
            db.update_analysis_task_status(user_id, task_id, "FAILED", str(exc))
            raise

        try:
            documents = self.get_knowledge_chunks_for_analysis(user_id, selected_document_ids or [])
            response = self.ai_service_client.analyze_jd(
                task_id=task_id,
                user_id=str(user_id),
                jd_text=jd_text,
                resume_text=resume_text,
                knowledge_texts=knowledge_texts or [],
                documents=documents,
                options=active_options,
            )
            data = response.get("data", {}) if isinstance(response, dict) else {}
            if isinstance(response, dict) and response.get("status") == "failed":
                db.save_workflow_logs(user_id, task_id, data.get("workflowLogs") or [])
                raise RuntimeError(response.get("error") or "ai-service analyze-jd failed")
            final_report = data.get("finalReport") or {}
            evidence_summary = data.get("evidenceSummary") or {}
            hallucination_control = data.get("hallucinationControl") or {}
            citations = data.get("citations") or []
            report_id = db.save_analysis_report(
                user_id=user_id,
                task_id=task_id,
                jd_text=jd_text,
                resume_text=resume_text,
                knowledge_texts=knowledge_texts or [],
                original_analysis=analysis,
                final_report=final_report,
                evidence_summary=evidence_summary,
                hallucination_control=hallucination_control,
                citations=citations,
                evidence_coverage=evidence_summary.get("evidenceCoverage"),
                hallucination_risk=hallucination_control.get("riskLevel", ""),
            )
            db.save_claim_check_results(
                user_id,
                task_id,
                data.get("verificationResults") or [],
            )
            db.save_workflow_logs(
                user_id,
                task_id,
                data.get("workflowLogs") or [],
            )
            db.save_quality_evaluation(
                user_id,
                task_id,
                data.get("qualityEvaluation") or {},
            )
            db.update_analysis_task_status(user_id, task_id, "SUCCESS")
            response["taskId"] = task_id
            response["reportId"] = report_id
            response["saved"] = True
            response["originalAnalysis"] = analysis.model_dump(mode="json")
            response["selectedDocumentIds"] = selected_document_ids or []
            return response
        except Exception as exc:  # noqa: BLE001
            db.update_analysis_task_status(user_id, task_id, "FAILED", str(exc))
            return {
                "taskId": task_id,
                "status": "failed",
                "saved": False,
                "warning": "增强校验服务暂不可用",
                "error": str(exc),
                "originalAnalysis": analysis.model_dump(mode="json"),
                "selectedDocumentIds": selected_document_ids or [],
                "data": {
                    "draftReport": {},
                    "finalReport": {},
                    "evidenceSummary": {},
                    "hallucinationControl": {
                        "riskLevel": "NOT_AVAILABLE",
                        "detectedItems": [],
                        "rewrittenItems": [],
                    },
                    "citations": [],
                    "claims": [],
                    "verificationResults": [],
                    "workflowLogs": ["ai-service unavailable; original JD analysis preserved"],
                    "qualityEvaluation": {},
                },
            }

    def create_analysis_task(self, user_id: int, task_id: str, **kwargs) -> int:
        return self.user_db(user_id).create_analysis_task(user_id=user_id, task_id=task_id, **kwargs)

    def update_analysis_task_status(
        self,
        user_id: int,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        self.user_db(user_id).update_analysis_task_status(user_id, task_id, status, error_message)

    def save_analysis_report(self, user_id: int, **kwargs) -> int:
        return self.user_db(user_id).save_analysis_report(user_id=user_id, **kwargs)

    def save_claim_check_results(
        self,
        user_id: int,
        task_id: str,
        verification_results: List[dict],
    ) -> None:
        self.user_db(user_id).save_claim_check_results(user_id, task_id, verification_results)

    def get_analysis_report(
        self,
        user_id: int,
        *,
        task_id: Optional[str] = None,
        report_id: Optional[int] = None,
    ) -> Optional[dict]:
        return self.user_db(user_id).get_analysis_report(user_id, task_id=task_id, report_id=report_id)

    def list_analysis_reports(self, user_id: int, limit: int = 20) -> List[dict]:
        return self.user_db(user_id).list_analysis_reports(user_id, limit)

    def get_claim_check_results(self, user_id: int, task_id: str) -> List[dict]:
        return self.user_db(user_id).get_claim_check_results(user_id, task_id)

    def save_workflow_logs(self, user_id: int, task_id: str, workflow_logs: List[dict]) -> None:
        self.user_db(user_id).save_workflow_logs(user_id, task_id, workflow_logs)

    def get_workflow_logs(self, user_id: int, task_id: str) -> List[dict]:
        return self.user_db(user_id).get_workflow_logs(user_id, task_id)

    def save_quality_evaluation(self, user_id: int, task_id: str, quality_evaluation: dict) -> None:
        self.user_db(user_id).save_quality_evaluation(user_id, task_id, quality_evaluation)

    def get_quality_evaluation(self, user_id: int, task_id: str) -> Optional[dict]:
        return self.user_db(user_id).get_quality_evaluation(user_id, task_id)

    def list_low_quality_reports(self, user_id: int, limit: int = 20) -> List[dict]:
        return self.user_db(user_id).list_low_quality_reports(user_id, limit)

    def upload_knowledge_document(
        self,
        user_id: int,
        uploaded_file,
        source_type: str,
        title: Optional[str] = None,
    ) -> dict:
        file_name = getattr(uploaded_file, "name", "") or "upload"
        db = self.user_db(user_id)
        document_id: Optional[int] = None
        try:
            raw_text, file_type = extract_text_from_uploaded_file(uploaded_file)
            doc_title = (title or "").strip() or file_name
            document_id = db.create_knowledge_document(
                user_id=user_id,
                title=doc_title,
                file_name=file_name,
                file_type=file_type,
                source_type=source_type,
                raw_text=raw_text,
                summary=raw_text[:240],
                status="PENDING",
            )
            chunks = build_knowledge_chunks(
                raw_text,
                document_id=document_id,
                source_type=source_type,
                file_name=file_name,
            )
            db.save_knowledge_chunks(user_id, document_id, chunks)
            db.update_knowledge_document_status(
                user_id,
                document_id,
                "READY",
                error_message="",
                chunk_count=len(chunks),
            )
            return db.get_knowledge_document(user_id, document_id) or {}
        except Exception as exc:
            if document_id is not None:
                db.update_knowledge_document_status(user_id, document_id, "FAILED", str(exc), 0)
                failed = db.get_knowledge_document(user_id, document_id)
                if failed:
                    return failed
            raise

    def list_knowledge_documents(
        self,
        user_id: int,
        source_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        return self.user_db(user_id).list_knowledge_documents(user_id, source_type, limit)

    def get_knowledge_chunks_for_analysis(
        self,
        user_id: int,
        document_ids: List[int],
    ) -> List[dict]:
        chunks = self.user_db(user_id).get_knowledge_chunks(user_id, document_ids)
        out: List[dict] = []
        for chunk in chunks:
            metadata = dict(chunk.get("metadata") or {})
            metadata.update(
                {
                    "fileName": chunk.get("file_name", ""),
                    "sourceType": chunk.get("source_type", "other"),
                    "chunkIndex": chunk.get("chunk_index", 0),
                    "documentTitle": chunk.get("title", ""),
                }
            )
            out.append(
                {
                    "documentId": str(chunk["document_id"]),
                    "chunkId": f"{chunk['document_id']}-{chunk['chunk_index']}",
                    "content": chunk.get("chunk_text", ""),
                    "metadata": metadata,
                }
            )
        return out

    def delete_knowledge_document(self, user_id: int, document_id: int) -> bool:
        return self.user_db(user_id).delete_knowledge_document(user_id, document_id)

    def search_courses(self, skills: List[str]) -> List[BilibiliCourse]:
        all_courses = []
        for skill in skills:
            courses = self.crawler.search_skill(skill)
            all_courses.extend(courses)
        return self.ranker.rank_by_skill(all_courses)

    def analyze_jd(self, user_id: int, jd_text: str) -> Tuple[JobAnalysis, List[BilibiliCourse]]:
        analysis = self.extract_skills(jd_text)
        courses = self.search_courses(analysis.skills)
        db = self.user_db(user_id)
        jd_record_id = db.save_jd_record(user_id, jd_text, analysis)
        db.save_courses(jd_record_id, courses)
        return analysis, courses

    def sync_to_practice_app(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> bool:
        return self.practice_invoker.invoke_practice_app(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
            auto_proceed=auto_proceed,
        )

    def build_practice_package_json(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
    ) -> str:
        return self.practice_invoker.build_skill_package_json(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
        )

    def build_practice_protocol_url(
        self,
        skills: List[str],
        practice_mode: Literal["direct", "ai_recommend"] = "direct",
        *,
        job_summary: str = "",
        difficulty: str = "",
        exam_options: Optional[Union[ExamOptionsForPractice, dict]] = None,
        auto_proceed: bool = False,
    ) -> str:
        return self.practice_invoker.build_protocol_url(
            skills,
            practice_mode,
            job_summary=job_summary,
            difficulty=difficulty,
            exam_options=exam_options,
            auto_proceed=auto_proceed,
        )

    def get_history(self, user_id: int, limit: int = 10) -> List[JDRecord]:
        return self.user_db(user_id).get_jd_records(user_id, limit)

    def get_jd_record(self, user_id: int, jd_record_id: int) -> Optional[JDRecord]:
        return self.user_db(user_id).get_jd_record_by_id(user_id, jd_record_id)

    def rename_jd_record(self, user_id: int, jd_record_id: int, display_name: Optional[str]) -> None:
        self.user_db(user_id).rename_jd_record(user_id, jd_record_id, display_name)

    def delete_jd_record(self, user_id: int, jd_record_id: int) -> None:
        self.user_db(user_id).delete_jd_record(user_id, jd_record_id)

    def generate_fit_exam(
        self,
        *,
        jd_text: str,
        skills: List[str],
        major_profile: str,
        question_count: int = 8,
    ) -> FitExamPaper:
        return self.ai_analyzer.generate_fit_exam(
            jd_text=jd_text,
            skills=skills,
            major_profile=major_profile,
            question_count=question_count,
        )

    def save_fit_exam_attempt(self, attempt: FitExamAttempt) -> int:
        if attempt.user_id is None:
            raise ValueError("user_id_required")
        return self.user_db(attempt.user_id).save_fit_exam_attempt(attempt)

    def list_job_postings(self, user_id: int, limit: int = 200) -> List[JobPosting]:
        return self.user_db(user_id).list_job_postings(user_id, limit)

    def add_job_posting(self, user_id: int, posting: JobPosting) -> int:
        posting.user_id = user_id
        db = self.user_db(user_id)
        job_id = db.insert_job_posting(posting)
        db.add_salary_snapshot(
            user_id,
            job_id,
            posting.salary_monthly_k,
            note="初始录入",
        )
        return job_id

    def refresh_job_salary_from_web(self, user_id: int, job_posting_id: int) -> Optional[float]:
        db = self.user_db(user_id)
        rows = db.list_job_postings(user_id, 500)
        target = next((j for j in rows if j.id == job_posting_id), None)
        if target is None or not (target.source_url or "").strip():
            return None
        url = target.source_url.strip()
        parsed, _plain = scrape_salary_from_url(url)
        if parsed is None:
            return None
        db.add_salary_snapshot(user_id, job_posting_id, parsed, note=f"页面抓取: {url}")
        db.update_job_posting_salary(user_id, job_posting_id, parsed)
        return parsed

    def get_salary_snapshots(self, user_id: int, job_posting_id: int) -> List[SalarySnapshot]:
        db = self.user_db(user_id)
        if not db.job_posting_belongs_to_user(user_id, job_posting_id):
            return []
        return db.get_salary_snapshots(user_id, job_posting_id)

    def predict_salary_for_job(self, user_id: int, job_posting_id: int) -> SalaryTrendPrediction:
        db = self.user_db(user_id)
        if not db.job_posting_belongs_to_user(user_id, job_posting_id):
            raise ValueError("job_not_found")
        snaps = db.get_salary_snapshots(user_id, job_posting_id)
        if not snaps:
            raise ValueError("没有薪酬历史，无法预测")
        history = [(s.observed_at, s.salary_monthly_k) for s in snaps]
        linear_hint = linear_next_forecast_k(history)
        lines = [
            f"{s.observed_at.strftime('%Y-%m-%d')} 月薪中值 {s.salary_monthly_k:.2f} 千元/月 · {s.note}"
            for s in snaps
        ]
        return self.ai_analyzer.predict_salary_trend(
            history_lines=lines,
            linear_hint=linear_hint,
            sample_count=len(snaps),
        )

    def latest_fit_scores(self, user_id: int) -> dict[int, Tuple[float, datetime]]:
        return self.user_db(user_id).get_latest_fit_score_by_jd(user_id)

    def generate_star_segment_suggestion(
        self,
        *,
        segment_type: str,
        input_text: str,
        jd_text: Optional[str] = None,
        resume_text: Optional[str] = None,
        current_star: Optional[dict] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> str:
        return self.ai_analyzer.generate_star_segment_suggestion(
            segment_type=segment_type,
            input_text=input_text,
            jd_text=jd_text,
            resume_text=resume_text,
            current_star=current_star,
            user_id=user_id,
            config_id=config_id,
        )

    def polish_star_story(
        self,
        *,
        situation: str,
        task: str,
        action: str,
        result: str,
        style: str = "standard",
        jd_text: Optional[str] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> str:
        return self.ai_analyzer.polish_star_story(
            situation=situation,
            task=task,
            action=action,
            result=result,
            style=style,
            jd_text=jd_text,
            user_id=user_id,
            config_id=config_id,
        )

    def smart_rewrite_star(
        self,
        *,
        original_text: str,
        style: str = "standard",
        jd_text: Optional[str] = None,
        user_id: Optional[Any] = None,
        config_id: Optional[str] = None,
    ) -> dict:
        return self.ai_analyzer.smart_rewrite_star(
            original_text=original_text,
            style=style,
            jd_text=jd_text,
            user_id=user_id,
            config_id=config_id,
        )

    def save_star_story(self, user_id: Any, story: StarStory) -> Any:
        return self.user_db(user_id).save_star_story(user_id, story)

    def list_star_stories(self, user_id: Any) -> List[dict]:
        return self.user_db(user_id).list_star_stories(user_id)

    def get_star_story(self, user_id: Any, story_id: Any) -> Optional[dict]:
        return self.user_db(user_id).get_star_story(user_id, story_id)

    def update_star_story(self, user_id: Any, story_id: Any, story: StarStory) -> bool:
        return self.user_db(user_id).update_star_story(user_id, story_id, story)

    def delete_star_story(self, user_id: Any, story_id: Any) -> bool:
        return self.user_db(user_id).delete_star_story(user_id, story_id)
