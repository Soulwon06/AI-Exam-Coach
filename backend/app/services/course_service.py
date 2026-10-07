from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import models
from app.core.errors import NotFoundError, InvalidRequestError


def create_course(db: Session, user: models.User, payload: dict) -> models.Course:
    name = (payload.get("name") or "").strip()
    if not name:
        raise InvalidRequestError("Course name is required")

    course = models.Course(
        user_id=user.id,
        name=name,
        school=payload.get("school"),
        teacher=payload.get("teacher"),
        exam_date=payload.get("exam_date"),
        status="CREATED",
    )
    db.add(course)
    db.flush()

    prefs = payload.get("preferences") or {}
    db.add(
        models.UserPreference(
            user_id=user.id,
            course_id=course.id,
            learning_mode=prefs.get("learning_mode", "EXPLANATION_FIRST"),
            simulation_mode=prefs.get("simulation_mode", "OPTIONAL"),
        )
    )
    db.add(
        models.Event(
            user_id=user.id,
            course_id=course.id,
            event_type="COURSE_CREATED",
            entity_type="course",
            entity_id=course.id,
        )
    )
    db.flush()
    return course


def get_course(db: Session, user: models.User, course_id: str) -> models.Course:
    course = db.get(models.Course, course_id)
    if course is None or course.user_id != user.id:
        raise NotFoundError("Course not found")
    return course


def update_exam_date(
    db: Session,
    user: models.User,
    course_id: str,
    exam_date: str | None,
) -> models.Course:
    course = get_course(db, user, course_id)
    normalized = exam_date.strip() if exam_date else None
    if normalized:
        try:
            datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError as exc:
            raise InvalidRequestError("exam_date must use YYYY-MM-DD format") from exc
    course.exam_date = normalized
    return course


def get_preference(db: Session, user_id: str, course_id: str) -> models.UserPreference | None:
    return (
        db.query(models.UserPreference)
        .filter(
            models.UserPreference.user_id == user_id,
            models.UserPreference.course_id == course_id,
        )
        .first()
    )


def days_remaining(course: models.Course) -> Optional[int]:
    if not course.exam_date:
        return None
    try:
        target = datetime.strptime(course.exam_date, "%Y-%m-%d").date()
        return (target - date.today()).days
    except (ValueError, TypeError):
        return None


def get_or_create_user(db: Session, user_id: Optional[str] = None) -> models.User:
    if user_id:
        user = db.get(models.User, user_id)
        if user:
            return user
    user = models.User(id=user_id or None)
    db.add(user)
    db.flush()
    return user
