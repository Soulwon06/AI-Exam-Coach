"""Practice Engine: one-question-at-a-time loop with immediate grading.
See docs/03_USER_FLOW.md, docs/10_API_CONTRACT.md.
"""
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.errors import QuestionNotAvailableError, SessionExpiredError
from app.services import scoring
from app.services.knowledge_base import get_canonical_study_unit
from app.services.question_trust import (
    assess_question,
    is_practice_trust_ready,
    leading_answer_letters,
    trusted_explanation,
)


CANONICAL_GRAPH_VERSION = "DATABASE_CANONICAL_GRAPH_V1"


def start_session(
    db: Session,
    user: models.User,
    course: models.Course,
    study_unit_id: str,
    mode: str = "EXPLANATION_FIRST",
    *,
    reuse_active: bool = True,
) -> models.LearningSession:
    unit = get_canonical_study_unit(db, study_unit_id, course.id)
    if unit is None:
        raise QuestionNotAvailableError("Study unit not found")
    if reuse_active:
        active = (
            db.query(models.LearningSession)
            .filter(
                models.LearningSession.user_id == user.id,
                models.LearningSession.course_id == course.id,
                models.LearningSession.study_unit_id == study_unit_id,
                models.LearningSession.completed_at.is_(None),
                ~models.LearningSession.current_state.like("QUESTION_RETRY:%"),
            )
            .order_by(models.LearningSession.started_at.desc(), models.LearningSession.id.desc())
            .first()
        )
        if active is not None:
            return active

    session = models.LearningSession(
        user_id=user.id,
        course_id=course.id,
        study_unit_id=study_unit_id,
        mode=mode,
        current_state="EXPLANATION" if mode == "EXPLANATION_FIRST" else "QUESTION",
    )
    db.add(session)
    db.add(
        models.LearningRecord(
            user_id=user.id,
            course_id=course.id,
            study_unit_id=study_unit_id,
            event_type="STARTED",
            metadata_={"source": "USER_ACTION", "study_preference": "ACTIVE"},
        )
    )
    db.flush()
    return session


def start_exact_wrong_question_retry(
    db: Session,
    user: models.User,
    course: models.Course,
    study_unit_id: str,
    question_id: str,
) -> models.LearningSession:
    """Start a question-first session pinned to one unresolved safe question."""

    unit = get_canonical_study_unit(db, study_unit_id, course.id)
    question = db.get(models.Question, question_id)
    if unit is None or question is None or question.course_id != course.id:
        raise QuestionNotAvailableError("Question is not available for this course")
    if not is_practice_trust_ready(question):
        raise QuestionNotAvailableError("Question structure is incomplete and cannot be practiced")

    latest = (
        db.query(models.PracticeRecord)
        .filter(
            models.PracticeRecord.user_id == user.id,
            models.PracticeRecord.question_id == question_id,
            models.PracticeRecord.study_unit_id == study_unit_id,
        )
        .order_by(models.PracticeRecord.created_at.desc(), models.PracticeRecord.id.desc())
        .first()
    )
    if latest is None or latest.correct:
        raise QuestionNotAvailableError("Question is not an unresolved wrong-book item")

    session = start_session(db, user, course, study_unit_id, "QUESTION_FIRST", reuse_active=False)
    if not _is_safe_question_for_session(db, session, question):
        raise QuestionNotAvailableError("Question is not available for this canonical study unit")
    # Reuse the persisted state column as a bounded retry cursor; no schema
    # migration or arbitrary question injection is introduced.
    session.current_state = f"QUESTION_RETRY:{question_id}"
    db.flush()
    return session


def get_session(
    db: Session,
    user: models.User,
    session_id: str,
    *,
    allow_completed: bool = False,
) -> models.LearningSession:
    s = db.get(models.LearningSession, session_id)
    if s is None or s.user_id != user.id:
        raise SessionExpiredError("Learning session not found")
    if s.completed_at is not None and not allow_completed:
        raise SessionExpiredError("Learning session already completed")
    return s


def next_question(
    db: Session,
    user: models.User,
    session: models.LearningSession,
) -> models.Question | None:
    if session.completed_at is not None:
        return None

    retry_prefix = "QUESTION_RETRY:"
    if session.current_state.startswith(retry_prefix):
        retry_question_id = session.current_state[len(retry_prefix) :]
        question = db.get(models.Question, retry_question_id)
        if question is not None and not db.query(models.PracticeRecord).filter(
            models.PracticeRecord.session_id == session.id,
            models.PracticeRecord.question_id == retry_question_id,
        ).first() and _is_safe_question_for_session(db, session, question):
            return question
        session.current_state = "QUESTION"

    # A legacy session must not re-enter the normal practice loop.
    if get_canonical_study_unit(db, session.study_unit_id, session.course_id) is None:
        complete_session(db, session)
        return None

    # Canonical graph practice has a stricter safety boundary than the legacy
    # path: only a safe primary mapping may drive a session. Secondary links
    # remain active evidence, but can never grant mastery credit for another
    # StudyUnit.
    unit = db.get(models.StudyUnit, session.study_unit_id)
    if unit is not None and unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        safe_questions = safe_canonical_questions(
            db,
            course_id=session.course_id,
            study_unit_id=session.study_unit_id,
        )
        qids = [question.id for question in safe_questions]
    else:
        # Preserve the established legacy behavior outside the canonical graph.
        unit_links = (
            db.query(models.QuestionStudyUnit)
            .filter(
                models.QuestionStudyUnit.study_unit_id == session.study_unit_id,
                models.QuestionStudyUnit.is_active.isnot(False),
            )
            .all()
        )
        legacy_questions = [db.get(models.Question, link.question_id) for link in unit_links]
        qids = [question.id for question in legacy_questions if question is not None and is_practice_trust_ready(question)]
    if not qids:
        complete_session(db, session)
        return None

    answered = (
        db.query(models.PracticeRecord.question_id)
        .filter(models.PracticeRecord.session_id == session.id)
        .all()
    )
    answered_ids = {r[0] for r in answered}

    candidates = [qid for qid in qids if qid not in answered_ids]
    if not candidates:
        complete_session(db, session)
        return None

    from app.core.errors import NotFoundError

    q = db.get(models.Question, candidates[0])
    if q is None:
        raise NotFoundError("Question not found")
    return q


def answer_question(
    db: Session,
    user: models.User,
    session: models.LearningSession,
    question_id: str,
    answer: str,
    time_spent: int,
) -> dict:
    q = db.get(models.Question, question_id)
    if q is None:
        raise QuestionNotAvailableError("Question not found")
    if not is_practice_trust_ready(q):
        raise QuestionNotAvailableError("Question structure is incomplete and cannot be practiced")

    session_unit = db.get(models.StudyUnit, session.study_unit_id)
    if session_unit is not None and session_unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        if not _is_safe_canonical_question_for_session(db, session, q):
            raise QuestionNotAvailableError("Question is not available for this canonical study session")
        unit_id = session.study_unit_id
    else:
        unit_id = _primary_unit_id(db, q.id) or session.study_unit_id

    correct = _is_correct(q, answer)

    record = models.PracticeRecord(
        session_id=session.id,
        question_id=q.id,
        user_id=user.id,
        study_unit_id=unit_id,
        answer=answer,
        correct=correct,
        time_spent=time_spent,
    )
    db.add(record)
    db.flush()

    scoring.update_mastery_after_answer(db, record)

    session.current_state = "ANSWER"
    # After answering, the loop continues to the next question.
    next_q = next_question(db, user, session)
    if next_q is None:
        next_action = "COMPLETE"
    else:
        next_action = "NEXT_QUESTION"

    knowledge_update = {
        "mastery_status": db.get(models.StudyUnit, unit_id).mastery_status if unit_id else "UNKNOWN",
        "practice_score": _practice_score(db, user.id, unit_id) if unit_id else 0,
    }

    db.add(
        models.Event(
            user_id=user.id,
            course_id=session.course_id,
            event_type="QUESTION_ANSWERED",
            entity_type="question",
            entity_id=q.id,
            payload={"correct": correct, "time_spent": time_spent},
        )
    )
    db.flush()

    teaching_feedback = _teaching_feedback(db, q, db.get(models.StudyUnit, unit_id))

    return {
        "correct": correct,
        "correct_answer": q.answer,
        "explanation": trusted_explanation(q.explanation, q.answer),
        "teaching_feedback": teaching_feedback,
        "knowledge_update": knowledge_update,
        "next_action": next_action,
        "next_question_id": next_q.id if next_q else None,
        "progress": session_progress(db, session),
    }


def _teaching_feedback(
    db: Session,
    question: models.Question,
    unit: models.StudyUnit | None,
) -> dict:
    """Project an honest, bounded teaching response after grading."""

    question_explanation = trusted_explanation(question.explanation, question.answer)
    unit_title = unit.title if unit is not None else "相关知识点"
    if question_explanation:
        return {
            "mode": "QUESTION_EXPLANATION",
            "title": "为什么",
            "explanation": question_explanation,
            "concept_evidence": [],
            "source": "题目解析",
            "study_unit_title": unit_title,
            "next_step": "记住这个判断依据，再继续下一题。",
        }

    concept_evidence = []
    if unit is not None:
        from app.services import student_learning_model

        projection = student_learning_model.explanation_projection(unit)
        if projection["explanation_mode"] in {
            student_learning_model.EXPLANATION_EVIDENCE,
            student_learning_model.STRUCTURE_ONLY,
        }:
            concept_evidence = [
                {
                    "excerpt": item["excerpt"],
                    "source": item.get("display_label") or item.get("source_file") or "课程资料",
                }
                for item in projection["evidence_items"]
            ]
    if concept_evidence:
        return {
            "mode": "CONCEPT_EVIDENCE",
            "title": "相关知识点资料",
            "explanation": "这道题暂无可靠逐题解析，下面是与本题知识点相关的课程资料。",
            "concept_evidence": concept_evidence,
            "source": "课程资料",
            "study_unit_title": unit_title,
            "next_step": "先回顾这个知识点，稍后再重做这道题。",
        }
    return {
        "mode": "ANSWER_ONLY",
        "title": "先记住正确答案",
        "explanation": "这道题暂无可靠逐题解析，暂不猜测你答错的具体原因。",
        "concept_evidence": [],
        "source": None,
        "study_unit_title": unit_title,
        "next_step": "可以先回到知识点查看内容，再继续练习。",
    }


def _is_correct(q: models.Question, answer: str) -> bool:
    """Grade a single answer by question type. Choice questions accept the option
    letter or its text; judgment questions accept 对/错/√/×/T/F; short answers are
    graded with keyword overlap against the stored reference answer. Questions
    without a usable stored answer can never be graded (correctly returns False).
    """
    truth = (q.answer or "").strip()
    if not truth:
        return False
    user = (answer or "").strip()

    assessment = assess_question(q)
    effective_type = assessment.effective_type
    if effective_type == "SINGLE_CHOICE":
        truth_letter = leading_answer_letters(truth) or _letters(truth)
        user_letter = _letters(user)
        if truth_letter:
            if user_letter:
                return user_letter == truth_letter
            return _matches_option_text(assessment.runtime_options, truth_letter, user)
        return _keyword_match(user, truth)

    if effective_type == "MULTIPLE_CHOICE":
        truth_letters = leading_answer_letters(truth) or _all_letters(truth)
        user_letters = leading_answer_letters(user) or _all_letters(user)
        return sorted(truth_letters) == sorted(user_letters) and bool(truth_letters)

    if q.type == "TRUE_FALSE":
        tv = _tf_value(truth)
        return bool(tv) and tv == _tf_value(user)

    return _keyword_match(user, truth)


def _letters(text: str) -> str:
    """First A-D letter found in text, normalized."""
    m = re.search(r"[A-D]", (text or "").upper())
    return m.group(0) if m else ""


def _all_letters(text: str) -> str:
    return "".join(re.findall(r"[A-D]", (text or "").upper()))


def _tf_value(value: str) -> str:
    v = (value or "").strip().lower()
    if v in ("t", "true", "对", "正确", "√", "yes", "y"):
        return "T"
    if v in ("f", "false", "错", "错误", "×", "no", "n"):
        return "F"
    return ""


def _matches_option_text(options: tuple[str, ...], letter: str, user: str) -> bool:
    for opt in options:
        if opt.strip().upper().startswith(letter):
            text = re.sub(r"^[A-D]\s*[.、．.)、]\s*", "", opt.strip())
            return text in user or user in text
    return False


def _keyword_match(user: str, truth: str) -> bool:
    """Short-answer grading: require most of the reference-answer character
    bigrams (order-aware) to also appear in the student answer."""
    truth_grams = set(_bigrams(truth))
    if not truth_grams:
        return False
    user_grams = set(_bigrams(user))
    if not user_grams:
        return False
    overlap = len(user_grams.intersection(truth_grams))
    return overlap / len(truth_grams) >= 0.6


def _bigrams(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "")
    return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]


def _primary_unit_id(db: Session, question_id: str) -> str | None:
    link = (
        db.query(models.QuestionStudyUnit)
        .filter(
            models.QuestionStudyUnit.question_id == question_id,
            models.QuestionStudyUnit.is_primary == True,  # noqa: E712
            models.QuestionStudyUnit.is_active.isnot(False),
        )
        .first()
    )
    return link.study_unit_id if link else None


def safe_canonical_question_query(
    db: Session,
    *,
    course_id: str,
    study_unit_id: str,
):
    """Return the single canonical practice eligibility contract.

    The course and StudyUnit are authoritative. A question must have
    an active primary link to that exact StudyUnit and satisfy every runtime
    practice safety predicate before it can be selected or answered.
    """
    return (
        db.query(models.Question)
        .join(models.QuestionStudyUnit, models.QuestionStudyUnit.question_id == models.Question.id)
        .filter(
            models.Question.id == models.QuestionStudyUnit.question_id,
            models.Question.course_id == course_id,
            models.QuestionStudyUnit.study_unit_id == study_unit_id,
            models.QuestionStudyUnit.is_primary.is_(True),
            models.QuestionStudyUnit.is_active.is_(True),
            models.Question.mapping_status == "MATCHED",
            models.Question.is_mapping_eligible.is_(True),
            models.Question.image_required.is_(False),
            models.Question.answer.isnot(None),
            func.trim(models.Question.answer) != "",
        )
    )


def safe_canonical_questions(
    db: Session,
    *,
    course_id: str,
    study_unit_id: str,
) -> list[models.Question]:
    """Materialize the shared SQL boundary plus the deterministic trust gate."""

    candidates = (
        safe_canonical_question_query(
            db,
            course_id=course_id,
            study_unit_id=study_unit_id,
        )
        .order_by(models.Question.created_at.asc(), models.Question.id.asc())
        .all()
    )
    return [question for question in candidates if is_practice_trust_ready(question)]


def safe_question_ids_for_session(db: Session, session: models.LearningSession) -> list[str]:
    unit = db.get(models.StudyUnit, session.study_unit_id)
    if unit is not None and unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        return [
            question.id
            for question in safe_canonical_questions(
                db,
                course_id=session.course_id,
                study_unit_id=session.study_unit_id,
            )
        ]
    links = (
        db.query(models.QuestionStudyUnit)
        .filter(
            models.QuestionStudyUnit.study_unit_id == session.study_unit_id,
            models.QuestionStudyUnit.is_active.isnot(False),
        )
        .all()
    )
    questions = [db.get(models.Question, link.question_id) for link in links]
    return [question.id for question in questions if question is not None and is_practice_trust_ready(question)]


def session_progress(db: Session, session: models.LearningSession) -> dict[str, int]:
    """Return a stable ordinal over the session's actual safe question set."""

    qids = safe_question_ids_for_session(db, session)
    answered_ids = {
        row[0]
        for row in db.query(models.PracticeRecord.question_id)
        .filter(models.PracticeRecord.session_id == session.id)
        .all()
    }
    answered = len(answered_ids.intersection(qids))
    total = len(qids)
    if session.completed_at is not None or answered >= total:
        return {"current": total, "total_estimated": total}
    return {"current": min(answered + 1, total), "total_estimated": total}


def _is_safe_canonical_question_for_session(
    db: Session,
    session: models.LearningSession,
    question: models.Question,
) -> bool:
    if not is_practice_trust_ready(question):
        return False
    return safe_canonical_question_query(
        db,
        course_id=session.course_id,
        study_unit_id=session.study_unit_id,
    ).filter(models.Question.id == question.id).first() is not None


def _is_safe_question_for_session(
    db: Session,
    session: models.LearningSession,
    question: models.Question,
) -> bool:
    unit = db.get(models.StudyUnit, session.study_unit_id)
    if unit is not None and unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        return _is_safe_canonical_question_for_session(db, session, question)
    return (
        question.course_id == session.course_id
        and is_practice_trust_ready(question)
        and db.query(models.QuestionStudyUnit)
        .filter(
            models.QuestionStudyUnit.question_id == question.id,
            models.QuestionStudyUnit.study_unit_id == session.study_unit_id,
            models.QuestionStudyUnit.is_active.isnot(False),
        )
        .first()
        is not None
    )


def _practice_score(db: Session, user_id: str, study_unit_id: str) -> int:
    from app.services.practice_metrics import practice_metrics

    unit = db.get(models.StudyUnit, study_unit_id)
    if unit is None:
        return 0
    return int(round(practice_metrics(db, user_id=user_id, unit=unit)["mastery_percent"]))


def complete_session(db: Session, session: models.LearningSession) -> None:
    if session.completed_at is None:
        session.current_state = "COMPLETED"
        session.completed_at = models.datetime.utcnow()
    db.flush()
