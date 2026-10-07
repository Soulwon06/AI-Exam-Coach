"""Scoring Engine. See docs/05_SCORING_ENGINE.md.

Computes Importance, Difficulty, Mastery, and course-level progress metrics.
Importance is derived from evidence (exam evidence has strongest default weight),
never from student errors. Student errors change Mastery/Weakness.
"""
from sqlalchemy.orm import Session

from app import models
from app.services.knowledge_base import canonical_study_unit_query

# Configuration (per docs/05: weights are configuration, not UI copy).
DEFAULT_IMPORTANCE_WEIGHTS = {
    "EXAM_FREQUENCY": 40.0,
    "EXAM_SCOPE": 25.0,
    "TEACHER_EMPHASIS": 15.0,
    "TEXTBOOK_CONTENT": 10.0,
    "VIDEO_CONTENT": 5.0,
    "CLASS_NOTE": 3.0,
    "HOMEWORK_PATTERN": 1.0,
    "LAB_CONTENT": 1.0,
}

RECENCY_WEIGHTS = [0.5, 0.3, 0.2]  # most recent answer carries most weight


def score_study_units(db: Session, course: models.Course) -> None:
    """Assign importance/difficulty/labels to all units of a course."""
    units = canonical_study_unit_query(db, course.id).all()
    if not units:
        return

    # Build evidence frequency per unit.
    evidence_counts = {u.id: {} for u in units}
    for u in units:
        for link in u.evidence_links:
            ev = db.get(models.Evidence, link.evidence_id)
            if ev is not None:
                et = ev.evidence_type
                evidence_counts[u.id][et] = evidence_counts[u.id].get(et, 0) + link.relevance_score

    for u in units:
        counts = evidence_counts[u.id]
        score = 0.0
        for et, weight in DEFAULT_IMPORTANCE_WEIGHTS.items():
            score += counts.get(et, 0) * weight
        # Clamp to 0..100
        score = max(0.0, min(100.0, score))
        u.importance_score = round(score, 2)
        u.importance_label = _label(score)
        if u.difficulty_score is None:
            u.difficulty_score = 50.0
    db.flush()


def _label(score: float) -> str:
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def update_mastery_after_answer(db: Session, record: models.PracticeRecord) -> None:
    """Recalculate coverage and mastery from the latest answer per question."""
    unit_id = record.study_unit_id
    if not unit_id:
        return
    unit = db.get(models.StudyUnit, unit_id)
    if unit is None:
        return

    from app.services.practice_metrics import practice_metrics

    metrics = practice_metrics(db, user_id=record.user_id, unit=unit)
    if not metrics["valid_question_count"]:
        return

    coverage_status = metrics["coverage_status"]
    # IN_PROGRESS is retained as the old database-compatible representation of
    # PARTIAL. The API exposes the precise PARTIAL status from practice_metrics.
    unit.coverage_status = "COVERED" if coverage_status == "COVERED" else "IN_PROGRESS" if coverage_status == "PARTIAL" else "NOT_STARTED"
    unit.progress = min(100, int(round(metrics["mastery_percent"])))

    if (
        not record.correct
        and metrics["attempted_question_count"] >= 2
        and metrics["latest_correct_count"] == 0
    ):
        unit.mastery_status = "REVIEW"
    elif coverage_status == "COVERED" and metrics["mastery_percent"] >= 80:
        unit.mastery_status = "MASTERED"
    elif metrics["mastery_percent"] >= 40:
        unit.mastery_status = "LEARNING"
    else:
        unit.mastery_status = "WEAK"
    db.flush()


def course_progress(db: Session, course: models.Course) -> dict:
    """Coverage, Mastery, Important Coverage, Important Mastery."""
    from app.services.student_learning_model import is_graph_course, course_progress as graph_course_progress

    if is_graph_course(db, course.id):
        return graph_course_progress(db, _progress_user(db, course), course)
    units = canonical_study_unit_query(db, course.id).all()
    if not units:
        return {
            "coverage": 0.0,
            "mastery": 0.0,
            "important_coverage": 0.0,
            "important_mastery": 0.0,
        }

    total = len(units)
    important = [u for u in units if u.importance_label == "HIGH"]

    from app.services.practice_metrics import practice_metrics

    metrics_by_unit = {u.id: practice_metrics(db, user_id=course.user_id, unit=u) for u in units}
    covered = [u for u in units if metrics_by_unit[u.id]["coverage_status"] == "COVERED"]
    mastered = [u for u in units if metrics_by_unit[u.id]["mastery_percent"] >= 80 and metrics_by_unit[u.id]["coverage_status"] == "COVERED"]

    important_total = len(important) or 1
    important_covered = [u for u in important if metrics_by_unit[u.id]["coverage_status"] == "COVERED"]
    important_mastered = [u for u in important if metrics_by_unit[u.id]["mastery_percent"] >= 80 and metrics_by_unit[u.id]["coverage_status"] == "COVERED"]

    return {
        "coverage": round(len(covered) / total * 100, 1),
        "mastery": round(len(mastered) / total * 100, 1),
        "important_coverage": round(len(important_covered) / important_total * 100, 1),
        "important_mastery": round(len(important_mastered) / important_total * 100, 1),
    }


def _progress_user(db: Session, course: models.Course) -> models.User:
    """Resolve the course owner without changing the legacy public signature."""
    return db.get(models.User, course.user_id) or models.User(id=course.user_id)


def recent_accuracy(db: Session, user_id: str, study_unit_id: str) -> float | None:
    from app.services.practice_metrics import practice_metrics

    unit = db.get(models.StudyUnit, study_unit_id)
    if unit is None:
        return None
    metrics = practice_metrics(db, user_id=user_id, unit=unit)
    if not metrics["attempted_question_count"]:
        return None
    return metrics["mastery_percent"]
