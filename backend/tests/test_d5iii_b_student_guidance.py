"""Focused D5-III-B contracts for honest feedback and small next actions."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.services import practice
from app.services import student_learning_model as slm
from app.services.question_trust import runtime_question_payload


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)(), engine


def _fixture(db, *, explanation=None):
    user = models.User(id="guidance-user")
    course = models.Course(id="guidance-course", user_id=user.id, name="数据库", status="READY")
    unit = models.StudyUnit(
        id="guidance-unit",
        course_id=course.id,
        title="GROUP BY",
        canonical_name="GROUP BY",
        canonical_kp_id="kp-guidance",
        canonical_graph_version=practice.CANONICAL_GRAPH_VERSION,
        mastery_status="UNKNOWN",
        coverage_status="NOT_STARTED",
    )
    question = models.Question(
        id="guidance-question",
        course_id=course.id,
        type="SINGLE_CHOICE",
        content="Which clause groups rows?",
        options=["A. WHERE", "B. GROUP BY"],
        answer="B",
        explanation=explanation,
        mapping_status="MATCHED",
        is_mapping_eligible=True,
        image_required=False,
        exam_year=2022,
        question_number="12",
        source_location="hash:block:00090",
    )
    db.add_all([user, course, unit, question])
    db.add(models.QuestionStudyUnit(question_id=question.id, study_unit_id=unit.id, is_primary=True, is_active=True))
    db.flush()
    return user, course, unit, question


def test_feedback_uses_trusted_question_explanation_only():
    db, engine = _db()
    try:
        _, _, unit, question = _fixture(db, explanation="GROUP BY groups rows by selected expressions.")
        feedback = practice._teaching_feedback(db, question, unit)
        assert feedback["mode"] == "QUESTION_EXPLANATION"
        assert feedback["explanation"].startswith("GROUP BY")
        assert feedback["concept_evidence"] == []
    finally:
        db.close()
        engine.dispose()


def test_feedback_uses_bounded_concept_evidence_without_claiming_exact_reason(monkeypatch):
    db, engine = _db()
    try:
        _, _, unit, question = _fixture(db)
        monkeypatch.setattr(slm, "_load_evidence", lambda: {
            "kp-guidance": {
                "evidence_status": "EXPLANATION_EVIDENCE",
                "explanation_evidence": [{
                    "source_file": "Database Textbook.pdf",
                    "location": "hash:block:00090",
                    "excerpt": "GROUP BY combines rows with equal grouping values. " * 40,
                    "match_method": "CANONICAL_ID",
                }],
                "structure_evidence": [],
            }
        })
        feedback = practice._teaching_feedback(db, question, unit)
        assert feedback["mode"] == "CONCEPT_EVIDENCE"
        assert "暂无可靠逐题解析" in feedback["explanation"]
        assert "这就是你做错的原因" not in feedback["explanation"]
        assert len(feedback["concept_evidence"][0]["excerpt"]) <= slm.MAX_EXPLANATION_EXCERPT_CHARS
        assert "hash:block" not in feedback["concept_evidence"][0]["source"]
    finally:
        db.close()
        engine.dispose()


def test_feedback_falls_back_honestly_without_question_or_concept_evidence(monkeypatch):
    db, engine = _db()
    try:
        _, _, unit, question = _fixture(db)
        monkeypatch.setattr(slm, "_load_evidence", lambda: {})
        feedback = practice._teaching_feedback(db, question, unit)
        assert feedback["mode"] == "ANSWER_ONLY"
        assert feedback["concept_evidence"] == []
        assert "暂不猜测" in feedback["explanation"]
    finally:
        db.close()
        engine.dispose()


def test_safe_exam_summary_is_deduplicated_and_source_display_is_human_readable():
    db, engine = _db()
    try:
        _, _, unit, question = _fixture(db)
        summary = slm._safe_exam_evidence_summary(db, unit)
        assert summary["safe_question_count"] == 1
        assert summary["exam_years"] == [2022]
        payload = runtime_question_payload(question)
        assert payload["source_display"]["label"] == "课程真题"
        assert "hash:block" not in str(payload["source_display"])
    finally:
        db.close()
        engine.dispose()


def test_action_batch_caps_and_keeps_unresolved_real_exam_work(monkeypatch):
    db, engine = _db()
    rows = [
        {"id": "weak", "study_preference": "ACTIVE", "exam_evidence_tier": "REAL_EXAM_ACTIVE", "mastery_status": "WEAK", "coverage_status": "COVERED", "practice_question_binding_ready": True, "ranking_position": 3, "title": "薄弱重点", "estimated_minutes": 10},
        {"id": "mastered", "study_preference": "ACTIVE", "exam_evidence_tier": "REAL_EXAM_ACTIVE", "mastery_status": "MASTERED", "coverage_status": "COVERED", "practice_question_binding_ready": True, "ranking_position": 1, "title": "已掌握", "estimated_minutes": 10},
        {"id": "supplementary", "study_preference": "ACTIVE", "exam_evidence_tier": "NO_REAL_EXAM_EVIDENCE_CURRENT_CORPUS", "mastery_status": "REVIEW", "coverage_status": "COVERED", "practice_question_binding_ready": True, "ranking_position": 2, "title": "补充", "estimated_minutes": 10},
        {"id": "deferred", "study_preference": "DEFERRED", "exam_evidence_tier": "REAL_EXAM_ACTIVE", "mastery_status": "WEAK", "coverage_status": "NOT_STARTED", "practice_question_binding_ready": True, "ranking_position": 0, "title": "暂后置", "estimated_minutes": 10},
    ]
    monkeypatch.setattr(slm, "is_graph_course", lambda *_args: True)
    monkeypatch.setattr(slm, "student_population", lambda *_args: rows)
    monkeypatch.setattr(slm, "_safe_exam_evidence_summary", lambda *_args: {"text": "已绑定 1 道可练真题"})
    course = type("CourseStub", (), {"id": "course"})()
    for phase, cap in (("STRENGTHENING", 5), ("COVERAGE", 4), ("FINAL_SPRINT", 3)):
        batch = slm.action_batch(db, None, course, phase, 2)
        assert len(batch["items"]) <= cap
        assert [item["id"] for item in batch["items"]] == ["weak"]
    assert "补充知识可以暂时后置" in slm.action_batch(db, None, course, "FINAL_SPRINT", 2)["reason"]
    db.close()
    engine.dispose()
