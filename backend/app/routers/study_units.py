from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.core.errors import NotFoundError, CourseNotReadyError
from app.database import get_db
from app.deps import current_user
from app.services import course_service, decision_engine, student_learning_model
from app.services.knowledge_base import get_canonical_study_unit

router = APIRouter()


@router.get("/study-units/{study_unit_id}")
def get_study_unit(study_unit_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    unit = get_canonical_study_unit(db, study_unit_id)
    if unit is None:
        raise NotFoundError("Study unit not found")
    course = course_service.get_course(db, user, unit.course_id)
    view = student_learning_model.unit_representation(db, user, course, unit)
    preference = course_service.get_preference(db, user.id, course.id)
    return {
        "data": {
            **view,
            "importance_text": {"HIGH": "高频", "MEDIUM": "重点", "LOW": "一般"}.get(unit.importance_label, ""),
            "source_type": unit.source_type,
            "learning_mode": preference.learning_mode if preference else "EXPLANATION_FIRST",
        },
        "error": None,
    }


@router.post("/study-units/{study_unit_id}/skip")
def skip_study_unit(study_unit_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    unit = get_canonical_study_unit(db, study_unit_id)
    if unit is None:
        raise NotFoundError("Study unit not found")
    course = course_service.get_course(db, user, unit.course_id)
    db.add(
        models.LearningRecord(
            user_id=user.id,
            course_id=course.id,
            study_unit_id=unit.id,
            event_type="SKIPPED",
            metadata_={"source": "USER_ACTION", "study_preference": "DEFERRED"},
        )
    )
    db.commit()
    return {"data": {"status": "SKIPPED", "study_preference": "DEFERRED", "mastery_status": "UNKNOWN" if unit.mastery_status == "SKIPPED" else unit.mastery_status}, "error": None}


@router.post("/study-units/{study_unit_id}/master")
def master_study_unit(study_unit_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    unit = get_canonical_study_unit(db, study_unit_id)
    if unit is None:
        raise NotFoundError("Study unit not found")
    course = course_service.get_course(db, user, unit.course_id)
    db.add(
        models.LearningRecord(
            user_id=user.id,
            course_id=course.id,
            study_unit_id=unit.id,
            event_type="MASTERED",
            metadata_={"source": "SELF_ASSESSED", "self_assessed_mastery": True},
        )
    )
    db.commit()
    return {"data": {**student_learning_model.unit_representation(db, user, course, unit), "self_assessed_mastery": True}, "error": None}
