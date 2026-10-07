"""Student practice metrics shared by mastery, progress, and recommendations.

Coverage is measured over the safe question set bound to one StudyUnit.  The
database column still keeps the legacy NOT_STARTED/IN_PROGRESS/COVERED values
for compatibility; this module exposes the precise student-facing status
without requiring a schema migration.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.services.question_trust import is_practice_trust_ready


def valid_question_ids(db: Session, unit: models.StudyUnit) -> set[str]:
    """Return the questions that are allowed to grant practice credit."""

    if unit.canonical_graph_version:
        # Import lazily because practice.py uses the scoring service and this
        # helper is also called from scoring.py.
        from app.services.practice import safe_canonical_questions

        return {
            question.id
            for question in safe_canonical_questions(
                db,
                course_id=unit.course_id,
                study_unit_id=unit.id,
            )
        }

    links = (
        db.query(models.QuestionStudyUnit)
        .filter(
            models.QuestionStudyUnit.study_unit_id == unit.id,
            models.QuestionStudyUnit.is_active.isnot(False),
        )
        .all()
    )
    question_ids: set[str] = set()
    for link in links:
        question = db.get(models.Question, link.question_id)
        if question is not None and is_practice_trust_ready(question):
            question_ids.add(question.id)
    return question_ids


def latest_attempts_by_question(
    db: Session,
    *,
    user_id: str,
    study_unit_id: str,
    question_ids: Iterable[str],
) -> dict[str, models.PracticeRecord]:
    """Keep only the latest attempt for each valid question."""

    allowed = set(question_ids)
    if not allowed:
        return {}
    records = (
        db.query(models.PracticeRecord)
        .filter(
            models.PracticeRecord.user_id == user_id,
            models.PracticeRecord.study_unit_id == study_unit_id,
        )
        .order_by(models.PracticeRecord.created_at.desc(), models.PracticeRecord.id.desc())
        .all()
    )
    latest: dict[str, models.PracticeRecord] = {}
    for record in records:
        if record.question_id in allowed and record.question_id not in latest:
            latest[record.question_id] = record
    return latest


def practice_metrics(db: Session, *, user_id: str, unit: models.StudyUnit) -> dict[str, Any]:
    """Calculate exposure-independent coverage and verified practice mastery."""

    question_ids = valid_question_ids(db, unit)
    latest = latest_attempts_by_question(
        db,
        user_id=user_id,
        study_unit_id=unit.id,
        question_ids=question_ids,
    )
    valid_count = len(question_ids)
    attempted_count = len(latest)
    latest_correct_count = sum(1 for record in latest.values() if record.correct)
    coverage_percent = round(attempted_count / valid_count * 100, 1) if valid_count else 0.0
    mastery_percent = round(latest_correct_count / attempted_count * 100, 1) if attempted_count else 0.0

    if not valid_count or not attempted_count:
        coverage_status = "NOT_COVERED"
    elif attempted_count < valid_count:
        coverage_status = "PARTIAL"
    else:
        coverage_status = "COVERED"

    return {
        "valid_question_count": valid_count,
        "attempted_question_count": attempted_count,
        "latest_correct_count": latest_correct_count,
        "coverage_percent": coverage_percent,
        "mastery_percent": mastery_percent,
        "coverage_status": coverage_status,
        "latest_attempts": latest,
    }
