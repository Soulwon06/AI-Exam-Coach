from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import models
from app.core.errors import NotFoundError, CourseNotReadyError
from app.schemas import CourseUpdate
from app.database import get_db
from app.deps import current_user
from app.services import course_service, decision_engine, practice, scoring
from app.services.knowledge_base import canonical_study_unit_query, evaluate_course_readiness
from app.services.material_service import material_out
from app.services import student_learning_model

router = APIRouter()


@router.post("/courses/{course_id}/archive")
def archive_course(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    course.status = "ARCHIVED"
    db.commit()
    return {"data": {"id": course.id, "status": course.status}, "error": None}


@router.get("/users/{user_id}/courses")
def list_courses(user_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if user_id != user.id:
        raise NotFoundError("User not found")
    courses = (
        db.query(models.Course).filter(models.Course.user_id == user.id).order_by(models.Course.created_at.desc()).all()
    )
    return {
        "data": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "exam_date": c.exam_date,
                "days_remaining": course_service.days_remaining(c),
                "progress": scoring.course_progress(db, c),
            }
            for c in courses
        ],
        "error": None,
    }


@router.post("/courses")
def create_course(payload: dict, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.create_course(db, user, payload)
    db.commit()
    return {
        "data": {
            "id": course.id,
            "name": course.name,
            "status": course.status,
        },
        "error": None,
    }


@router.get("/courses/{course_id}")
def get_course(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    return {
        "data": {
            "id": course.id,
            "name": course.name,
            "school": course.school,
            "teacher": course.teacher,
            "exam_date": course.exam_date,
            "days_remaining": course_service.days_remaining(course),
            "status": course.status,
            "progress": scoring.course_progress(db, course),
        },
        "error": None,
    }


@router.patch("/courses/{course_id}")
def update_course(
    course_id: str,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.update_exam_date(db, user, course_id, payload.exam_date)
    db.commit()
    db.refresh(course)
    return {
        "data": {
            "id": course.id,
            "name": course.name,
            "school": course.school,
            "teacher": course.teacher,
            "exam_date": course.exam_date,
            "days_remaining": course_service.days_remaining(course),
            "status": course.status,
            "progress": scoring.course_progress(db, course),
        },
        "error": None,
    }


@router.get("/courses/{course_id}/dashboard")
def dashboard(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    materials = (
        db.query(models.Material).filter(models.Material.course_id == course.id).order_by(models.Material.created_at.desc()).all()
    )
    progress = scoring.course_progress(db, course)
    readiness = evaluate_course_readiness(db, course.id)
    recommendation = {}
    action_batch = {}
    if course.status in ("READY", "LEARNING"):
        recommendation = decision_engine.get_recommendation(db, user, course)
        if recommendation:
            action_batch = student_learning_model.action_batch(
                db,
                user,
                course,
                recommendation.get("phase", "STRENGTHENING"),
                recommendation.get("days_remaining"),
            )
    review = decision_engine.review_items(db, user, course)

    return {
        "data": {
            "course": {
                "id": course.id,
                "name": course.name,
                "school": course.school,
                "teacher": course.teacher,
                "exam_date": course.exam_date,
                "days_remaining": course_service.days_remaining(course),
                "status": course.status,
            },
            "progress": progress,
            "recommendation": recommendation or None,
            "action_batch": action_batch or None,
            "review_items": review,
            "materials": [material_out(m) for m in materials],
            "readiness": readiness,
            "exam_focus": student_learning_model.exam_focus_summary(db, user, course),
        },
        "error": None,
    }


@router.get("/courses/{course_id}/progress")
def course_progress(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    return {"data": scoring.course_progress(db, course), "error": None}


@router.get("/courses/{course_id}/knowledge")
def knowledge(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    graph_view = student_learning_model.knowledge_view(db, user, course)
    if graph_view is not None:
        return {"data": graph_view, "error": None}
    domains = db.query(models.KnowledgeDomain).filter(models.KnowledgeDomain.course_id == course.id).all()
    result = []
    for d in domains:
        units = canonical_study_unit_query(db, course.id).filter(models.StudyUnit.domain_id == d.id).all()
        result.append(
            {
                "id": d.id,
                "title": d.title,
                "children": [
                    {
                        "id": u.id,
                        "title": u.title,
                        "importance_label": u.importance_label,
                        "importance_text": {"HIGH": "高频", "MEDIUM": "重点", "LOW": "一般"}.get(u.importance_label, ""),
                        "mastery_status": u.mastery_status,
                        "coverage_status": u.coverage_status,
                        "progress": u.progress,
                        "estimated_minutes": u.estimated_minutes,
                        "canonical_name": u.canonical_name,
                        "source_material_id": u.source_material_id,
                        "source_type": u.source_type,
                        "source_excerpt": u.source_excerpt,
                        "source_location": u.source_location,
                    }
                    for u in units
                ],
            }
        )
    return {"data": {"domains": result}, "error": None}


@router.get("/courses/{course_id}/review")
def review(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    return {"data": {"items": decision_engine.review_items(db, user, course)}, "error": None}


@router.get("/courses/{course_id}/wrong-book")
def wrong_book(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    return {"data": {"items": student_learning_model.wrong_book(db, user, course)}, "error": None}


@router.post("/courses/{course_id}/wrong-book/{question_id}/retry")
def retry_wrong_question(
    course_id: str,
    question_id: str,
    payload: dict = {},
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    study_unit_id = payload.get("study_unit_id")
    if not study_unit_id:
        raise InvalidRequestError("study_unit_id is required")
    session = practice.start_exact_wrong_question_retry(
        db, user, course, study_unit_id, question_id
    )
    db.commit()
    return {"data": {"session_id": session.id, "state": session.current_state}, "error": None}


@router.get("/courses/{course_id}/recommendation")
def recommendation(course_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    course = course_service.get_course(db, user, course_id)
    if course.status not in ("READY", "LEARNING"):
        raise CourseNotReadyError("Course is not ready yet")
    return {"data": decision_engine.get_recommendation(db, user, course), "error": None}
