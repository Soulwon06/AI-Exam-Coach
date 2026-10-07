from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.core.errors import NotFoundError, QuestionNotAvailableError
from app.database import get_db
from app.deps import current_user
from app.services import course_service, practice
from app.services.knowledge_base import get_canonical_study_unit
from app.services.question_trust import runtime_question_payload
from app.services import student_learning_model

router = APIRouter()


@router.post("/study-units/{study_unit_id}/start")
def start_learning(
    study_unit_id: str,
    payload: dict = {},
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    unit = get_canonical_study_unit(db, study_unit_id)
    if unit is None:
        raise NotFoundError("Study unit not found")
    course = course_service.get_course(db, user, unit.course_id)
    pref = course_service.get_preference(db, user.id, course.id)
    requested_mode = payload.get("mode")
    mode = requested_mode or (pref.learning_mode if pref else "EXPLANATION_FIRST")
    # An explicit mode is a deliberate new learning choice. The normal
    # preference-based entry may resume an unfinished session, while an
    # explicit QUESTION_FIRST/EXPLANATION_FIRST request must not silently
    # reuse a session created with the other mode.
    session = practice.start_session(
        db,
        user,
        course,
        study_unit_id,
        mode,
        reuse_active=requested_mode is None,
    )
    course.status = "LEARNING"
    db.commit()
    return {"data": {"session_id": session.id, "state": session.current_state}, "error": None}


@router.get("/learning-sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    s = practice.get_session(db, user, session_id, allow_completed=True)
    unit = db.get(models.StudyUnit, s.study_unit_id)
    return {
        "data": {
            "session_id": s.id,
            "course_id": s.course_id,
            "state": s.current_state,
            "mode": s.mode,
            "practice_question_binding_ready": bool(practice.safe_question_ids_for_session(db, s)),
            "study_unit": {
                "id": unit.id,
                "title": unit.title,
            } if unit else None,
        },
        "error": None,
    }


@router.get("/learning-sessions/{session_id}/explanation")
def get_explanation(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    s = practice.get_session(db, user, session_id)
    unit = db.get(models.StudyUnit, s.study_unit_id)
    course = db.get(models.Course, s.course_id)
    if unit is None or course is None:
        raise NotFoundError("Study unit not found")

    practice_ready = bool(practice.safe_question_ids_for_session(db, s))

    # Evidence-grounded explanation: graph courses use the deterministic
    # canonical evidence shadow; legacy courses retain persisted DB evidence.
    sources = []
    content_parts = []
    evidence_items = []
    explanation_mode = student_learning_model.GENERIC_FALLBACK
    evidence_status = "NO_EVIDENCE"
    for link in unit.evidence_links:
        ev = db.get(models.Evidence, link.evidence_id)
        if ev is not None:
            material = db.get(models.Material, ev.material_id)
            source_name = material.name if material else "课程资料"
            sources.append({"type": ev.evidence_type, "location": source_name, "display_label": source_name})
            if ev.content_reference:
                content_parts.append(ev.content_reference)

    if unit.canonical_graph_version == student_learning_model.CANONICAL_GRAPH_VERSION:
        projection = student_learning_model.explanation_projection(unit)
        explanation_mode = projection["explanation_mode"]
        evidence_status = projection["evidence_status"]
        evidence_items = projection["evidence_items"]
        sources.extend(projection["sources"])
    elif content_parts:
        explanation_mode = student_learning_model.EXPLANATION_EVIDENCE
        evidence_status = "PERSISTED_DB_EVIDENCE"

    if explanation_mode == student_learning_model.EXPLANATION_EVIDENCE:
        content_parts = content_parts or [item["excerpt"] for item in evidence_items]
        evidence_intro = "以下内容来自已绑定的课程资料证据："
    elif explanation_mode == student_learning_model.STRUCTURE_ONLY:
        evidence_intro = "已定位到课程结构来源，但当前没有足够的正文讲解证据。请结合原讲义对应章节理解本知识点。"
    else:
        evidence_intro = "当前没有可用的来源讲解证据；请结合原讲义或选择其他知识点继续学习。"

    next_step = (
        f"建议完成本单元对应真题练习，巩固掌握。预计用时 {unit.estimated_minutes} 分钟。"
        if practice_ready
        else "当前没有可安全作答的练习题；你可以返回课程查看原始资料，或选择其他知识点。"
    )

    explanation = (
        f"### {unit.title}\n\n"
        f"这是「{course.name}」中的重要知识点。\n\n"
        + evidence_intro
        + ("\n\n" + "\n\n".join(f"- {p}" for p in content_parts[:5]) if content_parts else "")
        + f"\n\n{next_step}"
    )
    return {
        "data": {
            "title": unit.title,
            "content": explanation,
            "sources": sources[:10],
            "explanation_mode": explanation_mode,
            "evidence_status": evidence_status,
            "evidence_items": evidence_items,
        },
        "error": None,
    }


@router.get("/learning-sessions/{session_id}/next-question")
def next_question(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    s = practice.get_session(db, user, session_id, allow_completed=True)
    q = practice.next_question(db, user, s)
    if q is None:
        db.commit()
        return {
            "data": {
                "status": "COMPLETE",
                "question": None,
                "progress": practice.session_progress(db, s),
            },
            "error": None,
        }
    return {
        "data": {
            "question": runtime_question_payload(q),
            "progress": practice.session_progress(db, s),
        },
        "error": None,
    }
@router.post("/questions/{question_id}/answer")
def answer_question(
    question_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    session_id = payload.get("session_id")
    if not session_id:
        raise NotFoundError("session_id is required")
    s = practice.get_session(db, user, session_id)
    result = practice.answer_question(
        db,
        user,
        s,
        question_id,
        payload.get("answer", ""),
        int(payload.get("time_spent", 0) or 0),
    )
    db.commit()
    return {"data": result, "error": None}
