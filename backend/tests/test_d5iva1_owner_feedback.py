"""Phase 2-D5-IV-A1 bounded owner-feedback contracts."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.routers import learning
from app.services import practice
from app.services import student_learning_model as slm


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False)()


def _course(db, *, learning_mode="EXPLANATION_FIRST", with_questions=False):
    user = models.User(id="owner-feedback-user")
    course = models.Course(id="owner-feedback-course", user_id=user.id, name="数据库系统", status="READY")
    unit = models.StudyUnit(
        id="owner-feedback-unit",
        course_id=course.id,
        title="GROUP BY",
        canonical_name="GROUP BY",
        source_type="TEXTBOOK",
    )
    preference = models.UserPreference(
        id="owner-feedback-preference",
        user_id=user.id,
        course_id=course.id,
        learning_mode=learning_mode,
        simulation_mode="OPTIONAL",
    )
    db.add_all([user, course, unit, preference])
    db.flush()
    if with_questions:
        for suffix in ("one", "two"):
            question = models.Question(
                id=f"owner-feedback-question-{suffix}",
                course_id=course.id,
                type="SHORT_ANSWER",
                content=f"Question {suffix}",
                answer="GROUP BY",
                source_type="REAL_EXAM",
                is_mapping_eligible=True,
                image_required=False,
            )
            db.add(question)
            db.flush()
            db.add(models.QuestionStudyUnit(question_id=question.id, study_unit_id=unit.id, is_primary=True, is_active=True))
        db.flush()
    return user, course, unit


def test_generic_start_respects_saved_explanation_first_preference():
    engine, db = _db()
    try:
        user, course, unit = _course(db, learning_mode="EXPLANATION_FIRST")
        result = learning.start_learning(unit.id, {}, db, user)["data"]
        session = db.get(models.LearningSession, result["session_id"])
        assert session.mode == "EXPLANATION_FIRST"
        assert session.current_state == "EXPLANATION"
    finally:
        db.close()
        engine.dispose()


def test_generic_start_respects_saved_question_first_preference_and_explicit_modes():
    engine, db = _db()
    try:
        user, course, unit = _course(db, learning_mode="QUESTION_FIRST")
        preferred = learning.start_learning(unit.id, {}, db, user)["data"]
        explicit_explanation = learning.start_learning(unit.id, {"mode": "EXPLANATION_FIRST"}, db, user)["data"]
        explicit_question = learning.start_learning(unit.id, {"mode": "QUESTION_FIRST"}, db, user)["data"]
        assert db.get(models.LearningSession, preferred["session_id"]).mode == "QUESTION_FIRST"
        assert db.get(models.LearningSession, explicit_explanation["session_id"]).mode == "EXPLANATION_FIRST"
        assert db.get(models.LearningSession, explicit_question["session_id"]).mode == "QUESTION_FIRST"
    finally:
        db.close()
        engine.dispose()


def test_no_practice_unit_can_start_explanation_and_session_exposes_no_practice():
    engine, db = _db()
    try:
        user, course, unit = _course(db, learning_mode="QUESTION_FIRST")
        started = learning.start_learning(unit.id, {"mode": "EXPLANATION_FIRST"}, db, user)["data"]
        session_data = learning.get_session(started["session_id"], db, user)["data"]
        assert session_data["course_id"] == course.id
        assert session_data["practice_question_binding_ready"] is False
        assert session_data["mode"] == "EXPLANATION_FIRST"
    finally:
        db.close()
        engine.dispose()


def test_no_practice_explanation_is_honest_about_the_missing_practice_action():
    engine, db = _db()
    try:
        user, course, unit = _course(db, learning_mode="QUESTION_FIRST")
        started = learning.start_learning(unit.id, {"mode": "EXPLANATION_FIRST"}, db, user)["data"]
        result = learning.get_explanation(started["session_id"], db, user)["data"]
        assert result["explanation_mode"] == slm.GENERIC_FALLBACK
        assert "没有可安全作答的练习题" in result["content"]
        assert "建议完成本单元对应真题练习" not in result["content"]
    finally:
        db.close()
        engine.dispose()


def test_exiting_after_one_answer_keeps_record_and_does_not_complete_session():
    engine, db = _db()
    try:
        user, course, unit = _course(db, learning_mode="QUESTION_FIRST", with_questions=True)
        started = practice.start_session(db, user, course, unit.id, "QUESTION_FIRST")
        first = practice.next_question(db, user, started)
        assert first is not None
        result = practice.answer_question(db, user, started, first.id, "wrong", 5)
        db.flush()
        assert result["next_action"] == "NEXT_QUESTION"
        assert db.query(models.PracticeRecord).filter_by(session_id=started.id).count() == 1
        assert started.completed_at is None
        assert started.current_state == "ANSWER"
    finally:
        db.close()
        engine.dispose()
