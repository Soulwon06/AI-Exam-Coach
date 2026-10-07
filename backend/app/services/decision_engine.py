"""Decision Engine. See docs/06_DECISION_ENGINE.md.

Chooses what the student should study next under time constraints:
Priority = f(Importance, Weakness, Urgency, Coverage, RemainingTime).

Time strategy:
- Earlier: emphasize important + weak.
- ~4 days before exam: increase coverage.
- ~2 days before: Final Sprint (important + weak), regardless of coverage.
"""
from datetime import date, datetime
from sqlalchemy.orm import Session

from app import models
from app.services.knowledge_base import canonical_study_unit_query

# Weakness = how far the student is from mastery on this unit.
_WEAK_STATUS = {"UNKNOWN", "WEAK", "LEARNING", "REVIEW", "NOT_STARTED"}


def _days_remaining(course: models.Course) -> int | None:
    if not course.exam_date:
        return None
    try:
        target = datetime.strptime(course.exam_date, "%Y-%m-%d").date()
        return (target - date.today()).days
    except (ValueError, TypeError):
        return None


def _phase(days: int | None) -> str:
    if days is None:
        return "STRENGTHENING"
    if days <= 2:
        return "FINAL_SPRINT"
    if days <= 4:
        return "COVERAGE"
    return "STRENGTHENING"


def _weakness(u: models.StudyUnit) -> float:
    if u.mastery_status == "MASTERED":
        return 0.0
    if u.mastery_status == "REVIEW":
        return 90.0
    if u.mastery_status == "WEAK":
        return 75.0
    if u.mastery_status == "LEARNING":
        return 55.0
    return 85.0  # UNKNOWN


def _availability(db: Session, u: models.StudyUnit) -> float:
    # Prefer units that have at least one mapped question or evidence.
    if u.question_links:
        return 1.0
    if u.evidence_links:
        return 0.8
    return 0.3


def compute_priority(
    u: models.StudyUnit,
    days: int | None,
    phase: str,
    progress: dict,
    coverage_status: str | None = None,
) -> tuple[float, str]:
    importance = u.importance_score or 0.0
    weakness = _weakness(u)

    if phase == "FINAL_SPRINT":
        # Importance and weakness dominate; coverage irrelevant.
        score = importance * 1.5 + weakness * 1.0
        reason = "FINAL_SPRINT: 考前强化最重要的知识"
        return score, reason

    urgency = 1.0
    if days is not None:
        urgency = max(1.0, (10 - days))  # closer to exam → higher urgency

    if phase == "COVERAGE":
        # Coverage dominates: prioritize high/medium importance units not yet covered.
        status = coverage_status or u.coverage_status
        coverage_bonus = 30.0 if status in ("NOT_STARTED", "NOT_COVERED") else 15.0 if status in ("IN_PROGRESS", "PARTIAL") else 0.0
        score = importance * 0.8 + weakness * 0.3 + coverage_bonus
        reason = "COVERAGE: 覆盖尚未学习的重点内容"
        return score, reason

    # STRENGTHENING
    score = importance * 0.9 + weakness * 0.8 + urgency * 2.0
    reason = "STRENGTHENING: 强化重要且薄弱的知识"
    return score, reason


def get_recommendation(db: Session, user: models.User, course: models.Course) -> dict:
    days = _days_remaining(course)
    phase = _phase(days)
    from app.services.student_learning_model import is_graph_course, recommendation as graph_recommendation

    if is_graph_course(db, course.id):
        return graph_recommendation(db, user, course, phase, days)
    progress = _progress_from(db, course)

    units = canonical_study_unit_query(db, course.id).all()
    if not units:
        return {}

    candidates = []
    from app.services.practice_metrics import practice_metrics
    for u in units:
        if u.mastery_status == "SKIPPED":
            continue
        availability = _availability(db, u)
        metrics = practice_metrics(db, user_id=user.id, unit=u)
        score, reason = compute_priority(u, days, phase, progress, metrics["coverage_status"])
        score = score * availability
        candidates.append((u, score, reason, availability))

    candidates.sort(key=lambda x: -x[1])
    if not candidates:
        return {}

    u, score, reason, availability = candidates[0]
    label_map = {"HIGH": "高频", "MEDIUM": "重点", "LOW": "一般"}
    reason_text = f"{reason}。{label_map.get(u.importance_label, '')}知识点，"
    if u.mastery_status in ("UNKNOWN", "NOT_STARTED"):
        reason_text += "尚未掌握。"
    elif u.mastery_status == "REVIEW":
        reason_text += "最近需要重新强化。"
    else:
        reason_text += "建议继续巩固。"
    if availability < 1:
        reason_text += "（当前可用资料较少）"

    return {
        "study_unit": {
            "id": u.id,
            "title": u.title,
            "importance_label": u.importance_label,
            "mastery_status": u.mastery_status,
            "coverage_status": metrics["coverage_status"],
            "coverage_percent": metrics["coverage_percent"],
            "mastery_percent": metrics["mastery_percent"],
            "progress": metrics["mastery_percent"],
            "estimated_minutes": u.estimated_minutes,
        },
        "reason": {"type": phase, "text": reason_text},
        "estimated_minutes": u.estimated_minutes,
        "phase": phase,
        "days_remaining": days,
    }


def _progress_from(db: Session, course: models.Course) -> dict:
    from app.services.scoring import course_progress

    return course_progress(db, course)


def review_items(db: Session, user: models.User, course: models.Course) -> list[dict]:
    from app.services.student_learning_model import is_graph_course, review_items as graph_review_items

    if is_graph_course(db, course.id):
        return graph_review_items(db, user, course)
    units = canonical_study_unit_query(db, course.id).all()
    from app.services.practice_metrics import practice_metrics

    items = []
    for u in units:
        if u.mastery_status not in ("WEAK", "REVIEW", "LEARNING"):
            continue
        metrics = practice_metrics(db, user_id=user.id, unit=u)
        acc = metrics["mastery_percent"] if metrics["attempted_question_count"] else None
        label_map = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
        items.append(
            {
                "study_unit_id": u.id,
                "title": u.title,
                "importance_label": u.importance_label,
                "importance_text": label_map.get(u.importance_label, "低"),
                "mastery_status": u.mastery_status,
                "recent_accuracy": acc,
                "estimated_minutes": u.estimated_minutes,
            }
        )
    items.sort(key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x["importance_label"], 3))
    return items
