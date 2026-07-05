from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    id: Optional[Any] = None
    username: str
    role: str = "user"
    created_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = True
    expires_at: Optional[datetime] = None
    generation_limit: int = 5
    remark: Optional[str] = None


class PersonalDecision(BaseModel):
    recommendation: Literal["APPLY", "CONSIDER", "SKIP"] = Field(
        default="CONSIDER",
        description="个人投递建议：APPLY=建议投递，CONSIDER=谨慎考虑，SKIP=暂不建议",
    )
    match_score: int = Field(default=50, ge=0, le=100, description="个人匹配度，0-100")
    decision_reasons: List[str] = Field(default_factory=list, description="投递判断的关键理由")
    critical_gaps: List[str] = Field(default_factory=list, description="影响投递质量的关键缺口")
    resume_rewrites: List[str] = Field(default_factory=list, description="可直接放入简历的改写表达")
    evidence_needed: List[str] = Field(default_factory=list, description="还需要补充证据的经历或材料")
    action_plan: List[str] = Field(default_factory=list, description="下一步行动清单")
    learning_plan: List[str] = Field(default_factory=list, description="可选学习或刷题建议")
    score_breakdown: Optional[dict] = Field(
        default=None,
        description="评分维度拆解：包括门槛过滤、技能匹配、经历相关性、加分项"
    )


class JobAnalysis(BaseModel):
    skills: List[str] = Field(..., description="从 JD 提取的技能列表")
    difficulty: str = Field(..., description="岗位难度评估：简单 / 中等 / 困难")
    job_summary: str = Field(..., description="岗位核心要求摘要")
    personal_decision: Optional[PersonalDecision] = Field(
        default=None,
        description="个人求职决策结果，旧历史记录可为空",
    )


class BilibiliCourse(BaseModel):
    title: str = Field(..., description="视频标题")
    url: str = Field(..., description="视频 URL")
    view_count: int = Field(..., description="播放量")
    favorite_count: int = Field(..., description="收藏数")
    like_count: int = Field(..., description="点赞数")
    coin_count: int = Field(default=0, description="投币数")
    danmaku_count: int = Field(default=0, description="弹幕数")
    publish_date: str = Field(..., description="发布日期")
    uploader: str = Field(..., description="UP 主")
    skill: str = Field(..., description="对应技能")
    rank_score: float = Field(default=0.0, description="推荐排序分数")
    duration: str = Field(default="", description="视频时长")
    description: str = Field(default="", description="视频描述")
    thumbnail: str = Field(default="", description="缩略图 URL")
    aid: int = Field(default=0, description="视频 AID")
    bvid: str = Field(default="", description="视频 BVID")


class JobContextForPractice(BaseModel):
    """传给刷题软件侧 AI 推荐模块的岗位上下文。"""

    difficulty: str = Field(default="", description="岗位难度")
    job_summary: str = Field(default="", description="岗位摘要，供刷题端理解场景")


class ExamOptionsForPractice(BaseModel):
    """与 AiSmartDrill 的 exam_options 对齐，使用 JSON snake_case。"""

    model_config = ConfigDict(extra="forbid")

    domain_hint: Optional[str] = Field(
        default=None,
        description="刷题领域提示，如 Python、数据库、前端等",
    )
    difficulty: Optional[str] = Field(
        default=None,
        description="简单 / 中等 / 困难；为空表示不限制",
    )
    question_count: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="本次组卷题量",
    )


class SkillPackage(BaseModel):
    """与 C# 刷题软件约定的技能包。"""

    model_config = ConfigDict(extra="forbid")

    skills: List[str] = Field(..., description="从 JD 提取的知识点或技能")
    practice_mode: Literal["direct", "ai_recommend"] = Field(
        ...,
        description="direct=直接刷题；ai_recommend=由刷题软件二次推荐题目",
    )
    job_context: JobContextForPractice = Field(
        default_factory=JobContextForPractice,
        description="岗位上下文，AI 推荐模式下建议提供",
    )
    exam_options: Optional[ExamOptionsForPractice] = Field(
        default=None,
        description="组卷与领域提示；省略时刷题端使用自身默认",
    )
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    version: str = Field(default="2.0", description="协议版本")
    source: str = Field(default="careerpath_ai", description="数据来源标识")


class JDRecord(BaseModel):
    id: Optional[Any] = None
    user_id: Optional[Any] = None
    jd_text: str
    analysis: JobAnalysis
    display_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class AnalysisTask(BaseModel):
    id: Optional[Any] = None
    user_id: Any
    task_id: str
    jd_id: Optional[Any] = None
    status: str = "PENDING"
    enable_rag: bool = True
    enable_verification: bool = True
    enable_hallucination_check: bool = True
    enable_rewrite: bool = True
    error_message: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AnalysisReport(BaseModel):
    id: Optional[Any] = None
    user_id: Any
    task_id: str
    jd_text: str = ""
    resume_text: str = ""
    knowledge_texts: List[str] = Field(default_factory=list)
    original_analysis: dict[str, Any] = Field(default_factory=dict)
    final_report: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    hallucination_control: dict[str, Any] = Field(default_factory=dict)
    citations: List[dict[str, Any]] = Field(default_factory=list)
    credibility_score: Optional[float] = None
    evidence_coverage: Optional[float] = None
    hallucination_risk: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ClaimCheckResult(BaseModel):
    id: Optional[Any] = None
    user_id: Any
    task_id: str
    claim_id: str = ""
    claim_text: str = ""
    claim_type: str = "GENERAL"
    check_status: str = ""
    confidence_score: float = 0.0
    evidence_count: int = 0
    reason: str = ""
    evidence: List[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class CourseRecord(BaseModel):
    id: Optional[Any] = None
    skill: str
    course: BilibiliCourse
    jd_record_id: Any
    created_at: datetime = Field(default_factory=datetime.now)


class FitExamQuestion(BaseModel):
    stem: str = Field(..., description="题干")
    options: List[str] = Field(..., min_length=2, max_length=6, description="选项列表")
    correct_index: int = Field(..., ge=0, description="正确选项下标，从 0 开始")
    category: str = Field(default="", description="题目类别")


class FitExamPaper(BaseModel):
    questions: List[FitExamQuestion] = Field(..., min_length=1, max_length=30)


class SalaryTrendPrediction(BaseModel):
    narrative: str = Field(..., description="走势与预测说明")
    forecast_next_k: Optional[float] = Field(
        default=None,
        description="下一观测点月薪中值，单位：千元/月",
    )
    methodology_note: str = Field(
        default="",
        description="风险提醒",
    )


class JobPosting(BaseModel):
    id: Optional[Any] = None
    user_id: Optional[Any] = None
    title: str
    company: str = ""
    region: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    transit_minutes: Optional[int] = None
    salary_monthly_k: float = Field(..., description="当前月薪中值，单位：千元/月")
    jd_record_id: Optional[Any] = None
    source_url: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class SalarySnapshot(BaseModel):
    id: Optional[int] = None
    job_posting_id: int
    observed_at: datetime = Field(default_factory=datetime.now)
    salary_monthly_k: float
    note: str = ""


class FitExamAttempt(BaseModel):
    id: Optional[Any] = None
    user_id: Optional[Any] = None
    jd_record_id: Optional[Any] = None
    major_profile: str = ""
    paper: FitExamPaper
    answers: List[int] = Field(default_factory=list, description="用户每题所选下标")
    score: float = Field(..., ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.now)
