import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class APISuccess(BaseModel):
    data: dict = {}
    error: dict | None = None


class APIError(BaseModel):
    data: dict | None = None
    error: dict = {}


class RankingItemOut(BaseModel):
    canonical_kp_id: str
    name_cn: Optional[str] = None
    name_en: Optional[str] = None
    ranking_position: int
    ranking_score: float
    display_priority_score: float
    display_score_is_probability: bool = False
    ranking_entity_role: str
    exam_evidence_tier: str
    evidence_aggregation_mode: str
    question_occurrence_count: int
    primary_question_occurrence_count: int
    secondary_question_occurrence_count: int
    year_coverage_count: int
    year_denominator: int
    paper_coverage_count: int
    paper_denominator: int
    textbook_evidence_status: Optional[str] = None
    textbook_support_signal: float
    ranking_reason_codes: List[str]
    study_unit_id: Optional[str] = None
    study_unit_binding_status: str = "NOT_MATERIALIZED"
    mastery_status: Optional[str] = None
    coverage_status: Optional[str] = None
    progress: Optional[int] = None
    estimated_minutes: Optional[int] = None
    practice_question_binding_ready: bool = False


class RankingDataOut(BaseModel):
    policy_version: str
    ranking_view: str
    score_semantics: str
    total: int
    filtered_total: int
    offset: int
    limit: int
    items: List[RankingItemOut] = Field(default_factory=list)
    study_unit_materialization: dict | None = None


class RankingAPIResponse(BaseModel):
    data: RankingDataOut | None = None
    error: dict | None = None


# ---------- Auth / User ----------

class UserOut(BaseModel):
    id: str
    created_at: Optional[datetime] = None


# ---------- Courses ----------

class PreferenceIn(BaseModel):
    learning_mode: str = "EXPLANATION_FIRST"
    simulation_mode: str = "OPTIONAL"


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    school: Optional[str] = None
    teacher: Optional[str] = None
    exam_date: Optional[str] = None
    preferences: Optional[PreferenceIn] = None


class CourseUpdate(BaseModel):
    exam_date: Optional[str]


class CourseOut(BaseModel):
    id: str
    name: str
    school: Optional[str] = None
    teacher: Optional[str] = None
    exam_date: Optional[str] = None
    status: str
    days_remaining: Optional[int] = None
    created_at: Optional[datetime] = None


class ProgressOut(BaseModel):
    coverage: float = 0.0
    mastery: float = 0.0
    important_coverage: float = 0.0
    important_mastery: float = 0.0


class RecommendationOut(BaseModel):
    study_unit: dict
    reason: dict
    estimated_minutes: int


class DashboardOut(BaseModel):
    course: dict
    progress: dict
    recommendation: Optional[dict] = None
    review_items: List[dict] = []
    materials: List[dict] = []


# ---------- Materials ----------

class MaterialOut(BaseModel):
    id: str
    course_id: str
    type: str
    source: Optional[str] = None
    name: str
    external_url: Optional[str] = None
    status: str
    progress: int
    error_code: Optional[str] = None
    parsing_status: Optional[str] = None
    parser_method: Optional[str] = None
    parser_version: Optional[str] = None
    extracted_char_count: Optional[int] = None
    extraction_quality: Optional[str] = None
    extraction_error: Optional[str] = None
    file_hash: Optional[str] = None
    extracted_text_sample: str = ""


class MaterialUrlIn(BaseModel):
    type: str
    url: str


# ---------- Knowledge ----------

class StudyUnitOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    importance_label: Optional[str] = None
    mastery_status: str
    coverage_status: str
    progress: int
    estimated_minutes: int
    canonical_name: Optional[str] = None
    canonical_kp_id: Optional[str] = None
    canonical_graph_version: Optional[str] = None
    source_material_id: Optional[str] = None
    source_type: Optional[str] = None
    source_excerpt: Optional[str] = None
    source_location: Optional[str] = None


class DomainOut(BaseModel):
    id: str
    title: str
    children: List[dict] = []


# ---------- Learning ----------

class SessionStartOut(BaseModel):
    session_id: str
    state: str


class SessionOut(BaseModel):
    session_id: str
    state: str
    study_unit: Optional[dict] = None
    question: Optional[dict] = None


class ExplanationOut(BaseModel):
    title: str
    content: str
    sources: List[dict] = []


class QuestionOut(BaseModel):
    id: str
    type: str
    content: str
    options: Optional[list] = None
    assessment_target: Optional[str] = None
    segmentation_status: Optional[str] = None
    content_quality: Optional[str] = None
    segmentation_provenance: Optional[dict] = None
    effective_question_context: Optional[str] = None
    is_mapping_eligible: Optional[bool] = None


class NextQuestionOut(BaseModel):
    question: dict
    progress: dict


class AnswerIn(BaseModel):
    session_id: str
    answer: str
    time_spent: int = 0


class AnswerOut(BaseModel):
    correct: bool
    correct_answer: str
    explanation: Optional[str] = None
    knowledge_update: dict
    next_action: str


# ---------- Review ----------

class ReviewItem(BaseModel):
    study_unit_id: str
    title: str
    importance_label: str
    mastery_status: str
    recent_accuracy: Optional[float] = None
