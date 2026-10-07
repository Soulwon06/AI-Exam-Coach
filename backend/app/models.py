import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


UUID = PGUUID(as_uuid=True) if False else String(36)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    created_at = Column(DateTime, default=datetime.utcnow)

    courses = relationship("Course", back_populates="user")


class AuthAccount(Base):
    __tablename__ = "auth_accounts"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    username = Column(String(32), nullable=False, unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Course(Base):
    __tablename__ = "courses"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    school = Column(String(200), nullable=True)
    teacher = Column(String(200), nullable=True)
    exam_date = Column(String(50), nullable=True)  # ISO date string
    status = Column(
        Enum("CREATED", "ANALYZING", "READY", "LEARNING", "ARCHIVED", name="course_status"),
        default="CREATED",
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="courses")
    materials = relationship("Material", back_populates="course", cascade="all, delete-orphan")
    domains = relationship("KnowledgeDomain", back_populates="course", cascade="all, delete-orphan")
    study_units = relationship("StudyUnit", back_populates="course", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="course", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="course", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False)
    learning_mode = Column(
        Enum("EXPLANATION_FIRST", "QUESTION_FIRST", name="learning_mode"),
        default="EXPLANATION_FIRST",
        nullable=False,
    )
    simulation_mode = Column(
        Enum("OPTIONAL", "ENABLED", "DISABLED", name="simulation_mode"),
        default="OPTIONAL",
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Material(Base):
    __tablename__ = "materials"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    type = Column(
        Enum(
            "REAL_EXAM",
            "EXAM_SCOPE",
            "TEACHER_PPT",
            "TEXTBOOK",
            "BILIBILI",
            "CLASS_NOTES",
            "HOMEWORK",
            "LAB",
            "OTHER",
            name="material_type",
        ),
        nullable=False,
    )
    source = Column(String(50), nullable=True)  # "upload" | "url"
    name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=True)
    external_url = Column(Text, nullable=True)
    status = Column(
        Enum("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="material_status"),
        default="PENDING",
        nullable=False,
    )
    # Parsing is deliberately tracked separately from the async material/job
    # status above.  COMPLETED means the worker finished; parsing_status says
    # whether usable source text was actually produced.
    parsing_status = Column(
        Enum(
            "PENDING", "PROCESSING", "PARSED", "LOW_QUALITY", "FAILED", "UNSUPPORTED",
            name="material_parsing_status",
        ),
        default="PENDING",
        nullable=False,
    )
    parser_method = Column(String(50), nullable=True)
    parser_version = Column(String(50), nullable=True)
    extracted_text = Column(Text, nullable=True)
    extracted_char_count = Column(Integer, nullable=True)
    extraction_quality = Column(String(20), nullable=True)  # HIGH / LOW / NONE
    extraction_error = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    progress = Column(Integer, default=0)
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    course = relationship("Course", back_populates="materials")
    evidences = relationship("Evidence", back_populates="material", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidences"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    material_id = Column(String(36), ForeignKey("materials.id"), nullable=False, index=True)
    evidence_type = Column(
        Enum(
            "EXAM_FREQUENCY",
            "EXAM_SCOPE",
            "TEACHER_EMPHASIS",
            "TEXTBOOK_CONTENT",
            "VIDEO_CONTENT",
            "CLASS_NOTE",
            "HOMEWORK_PATTERN",
            "LAB_CONTENT",
            name="evidence_type",
        ),
        nullable=False,
    )
    content_reference = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    material = relationship("Material", back_populates="evidences")


class KnowledgeDomain(Base):
    __tablename__ = "knowledge_domains"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    parent_id = Column(String(36), ForeignKey("knowledge_domains.id"), nullable=True)
    title = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="domains")
    study_units = relationship("StudyUnit", back_populates="domain")


class StudyUnit(Base):
    __tablename__ = "study_units"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    domain_id = Column(String(36), ForeignKey("knowledge_domains.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # Course Knowledge Base v1: the canonical title and its auditable teaching
    # source. Legacy units may keep these fields NULL.
    canonical_name = Column(String(200), nullable=True, index=True)
    canonical_kp_id = Column(String(64), nullable=True, index=True)
    canonical_graph_version = Column(String(80), nullable=True, index=True)
    source_material_id = Column(String(36), ForeignKey("materials.id"), nullable=True, index=True)
    source_type = Column(String(50), nullable=True)
    source_excerpt = Column(Text, nullable=True)
    source_location = Column(String(100), nullable=True)

    importance_score = Column(Float, default=0.0)
    difficulty_score = Column(Float, default=0.0)
    importance_label = Column(String(20), nullable=True)  # HIGH / MEDIUM / LOW

    mastery_status = Column(
        Enum("UNKNOWN", "WEAK", "LEARNING", "MASTERED", "REVIEW", "SKIPPED", name="mastery_status"),
        default="UNKNOWN",
        nullable=False,
    )
    coverage_status = Column(
        Enum("NOT_STARTED", "IN_PROGRESS", "COVERED", name="coverage_status"),
        default="NOT_STARTED",
        nullable=False,
    )
    progress = Column(Integer, default=0)  # 0-100
    estimated_minutes = Column(Integer, default=10)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    course = relationship("Course", back_populates="study_units")
    domain = relationship("KnowledgeDomain", back_populates="study_units")
    question_links = relationship(
        "QuestionStudyUnit", back_populates="study_unit", cascade="all, delete-orphan"
    )
    evidence_links = relationship(
        "StudyUnitEvidence", back_populates="study_unit", cascade="all, delete-orphan"
    )


class StudyUnitEvidence(Base):
    __tablename__ = "study_unit_evidences"

    study_unit_id = Column(String(36), ForeignKey("study_units.id"), primary_key=True)
    evidence_id = Column(String(36), ForeignKey("evidences.id"), primary_key=True)
    relevance_score = Column(Float, default=0.5)

    study_unit = relationship("StudyUnit", back_populates="evidence_links")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    parent_question_id = Column(String(36), ForeignKey("questions.id"), nullable=True)
    source_type = Column(
        Enum("REAL_EXAM", "AI_GENERATED", "OTHER", name="source_type"),
        default="REAL_EXAM",
        nullable=False,
    )
    type = Column(
        Enum(
            "SINGLE_CHOICE",
            "MULTIPLE_CHOICE",
            "TRUE_FALSE",
            "FILL_BLANK",
            "SHORT_ANSWER",
            "CALCULATION",
            "PROBLEM_SOLVING",
            "DRAWING",
            "OTHER",
            name="question_type",
        ),
        default="SINGLE_CHOICE",
        nullable=False,
    )
    content = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=True)
    difficulty_score = Column(Float, nullable=True)
    assessment_target = Column(String(255), nullable=True)
    image_required = Column(Boolean, default=False)
    # Exam Intelligence v1 provenance and deterministic identity.
    source_material_id = Column(String(36), ForeignKey("materials.id"), nullable=True, index=True)
    exam_year = Column(Integer, nullable=True)
    question_number = Column(String(20), nullable=True)
    subquestion_number = Column(String(20), nullable=True)
    source_location = Column(String(100), nullable=True)
    raw_source_text = Column(Text, nullable=True)
    extraction_method = Column(String(50), nullable=True)
    extraction_version = Column(String(50), nullable=True)
    fingerprint = Column(String(64), nullable=True, index=True)
    mapping_status = Column(
        Enum("PENDING", "MATCHED", "AMBIGUOUS", "UNMATCHED", name="question_mapping_status"),
        default="PENDING",
        nullable=False,
    )
    mapping_confidence = Column(Float, nullable=True)
    mapping_method = Column(String(50), nullable=True)
    mapping_version = Column(String(50), nullable=True)
    # Question Intelligence Quality Gate.  These fields are additive so the
    # original question text/provenance remain available for audit.
    segmentation_status = Column(String(40), default="PASS", nullable=True)
    content_quality = Column(String(40), default="PASS", nullable=True)
    content_quality_reason = Column(Text, nullable=True)
    # Optional v1 segmentation evidence.  Legacy questions remain valid with
    # this field NULL; new segmentation runs may persist a bounded JSON record.
    segmentation_provenance = Column(JSON, nullable=True)
    effective_question_context = Column(Text, nullable=True)
    is_mapping_eligible = Column(Boolean, default=True, nullable=True, index=True)
    segmentation_is_current = Column(Boolean, default=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="questions")
    source_material = relationship("Material", foreign_keys=[source_material_id])
    study_unit_links = relationship(
        "QuestionStudyUnit", back_populates="question", cascade="all, delete-orphan"
    )
    exam_evidences = relationship("ExamEvidence", back_populates="question", cascade="all, delete-orphan")


class QuestionStudyUnit(Base):
    __tablename__ = "question_study_units"

    question_id = Column(String(36), ForeignKey("questions.id"), primary_key=True)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), primary_key=True)
    is_primary = Column(Boolean, default=False)
    relevance_score = Column(Float, default=0.5)
    is_active = Column(Boolean, default=True, nullable=True)
    invalidated_reason = Column(String(100), nullable=True)

    question = relationship("Question", back_populates="study_unit_links")
    study_unit = relationship("StudyUnit", back_populates="question_links")


class ExamEvidence(Base):
    """Auditable link from a real exam question to an existing StudyUnit."""

    __tablename__ = "exam_evidences"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    question_id = Column(String(36), ForeignKey("questions.id"), nullable=False, index=True)
    source_material_id = Column(String(36), ForeignKey("materials.id"), nullable=False, index=True)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=False, index=True)
    exam_year = Column(Integer, nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    relevance_score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    source_location = Column(String(100), nullable=True)
    mapping_method = Column(String(50), nullable=True)
    mapping_version = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=True)
    invalidated_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    question = relationship("Question", back_populates="exam_evidences")


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=False)
    mode = Column(
        Enum("EXPLANATION_FIRST", "QUESTION_FIRST", name="session_mode"),
        default="EXPLANATION_FIRST",
        nullable=False,
    )
    current_state = Column(String(50), default="START", nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class PracticeRecord(Base):
    __tablename__ = "practice_records"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("learning_sessions.id"), nullable=False, index=True)
    question_id = Column(String(36), ForeignKey("questions.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=True, index=True)
    answer = Column(Text, nullable=True)
    correct = Column(Boolean, nullable=False)
    time_spent = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LearningRecord(Base):
    __tablename__ = "learning_records"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=True, index=True)
    event_type = Column(
        Enum("STARTED", "COMPLETED", "SKIPPED", "MASTERED", "REVIEWED", name="learning_event"),
        nullable=False,
    )
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=False)
    reason_type = Column(String(100), nullable=True)
    reason_text = Column(Text, nullable=True)
    score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="recommendations")
    study_unit = relationship("StudyUnit")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(String(36), nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PilotKnowledgePoint(Base):
    """Structured metadata for the bounded database-system validation pilot."""

    __tablename__ = "pilot_knowledge_points"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    study_unit_id = Column(String(36), ForeignKey("study_units.id"), nullable=False, unique=True, index=True)
    name_cn = Column(String(200), nullable=False)
    name_en = Column(String(200), nullable=False)
    parent = Column(String(200), nullable=True)
    chapter = Column(String(100), nullable=True)
    section = Column(String(255), nullable=True)
    definition = Column(Text, nullable=True)
    core_rule = Column(Text, nullable=True)
    mechanism = Column(Text, nullable=True)
    example = Column(Text, nullable=True)
    common_mistakes = Column(Text, nullable=True)
    related_concepts = Column(JSON, nullable=True)
    source_file = Column(String(255), nullable=False)
    source_section = Column(String(255), nullable=True)
    studyunit_status = Column(String(40), nullable=False, default="PILOT")
    created_at = Column(DateTime, default=datetime.utcnow)

    study_unit = relationship("StudyUnit")


class PilotQuestionEnrichment(Base):
    """Validated, bounded LLM enrichment for one pilot question."""

    __tablename__ = "pilot_question_enrichments"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    question_id = Column(String(36), ForeignKey("questions.id"), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False)
    mapping_reason = Column(Text, nullable=True)
    knowledge_explanation = Column(Text, nullable=True)
    solution_explanation = Column(Text, nullable=True)
    related_concepts = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    provider = Column(String(80), nullable=True)
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    question = relationship("Question")
