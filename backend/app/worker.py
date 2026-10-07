"""Background worker for material processing.

Per docs/08_AI_PIPELINE.md async jobs and docs/11 Phase 5, heavy work (parsing,
extraction, Course Brain building) runs outside the API request path. This MVP uses
a bounded thread pool so no extra infrastructure is required; swap for Celery/RQ
when deploying PostgreSQL in production.

Concurrency design:
- Multiple materials from the same upload are parsed in parallel (up to
  MAX_WORKERS). Unbounded threads cost memory and make DB lock contention worse.
- Course-level scoring + READY transition runs exactly once per batch: the last
  still-running worker for a course "finalizes" it, so N files never trigger N
  full re-scores.
"""
import threading
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.core.config import settings
from app.services import course_brain
from app.services.knowledge_base import build_course_knowledge_base, evaluate_course_readiness

MAX_WORKERS = getattr(settings, "max_workers", 4)

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="aiec-worker")
_pool_lock = threading.Lock()
# course_id -> number of materials still in flight for that course.
_course_inflight: dict[str, int] = defaultdict(int)
logger = logging.getLogger(__name__)


def _run(material_id: str) -> None:
    course_id: str | None = None
    db: Session = SessionLocal()
    try:
        material = db.get(models.Material, material_id)
        if material is None:
            return
        course_id = material.course_id
        material.status = "PROCESSING"
        material.progress = 10
        db.commit()

        material = db.get(models.Material, material_id)
        course_brain.process_material(db, material)

        # Material result is committed immediately; course scoring is deferred
        # to the batch finalizer (next block) to avoid N full re-scores.
        db.commit()
    except Exception:
        db.rollback()
        m = db.get(models.Material, material_id)
        if m is not None:
            m.status = "FAILED"
            m.error_code = "AI_PROCESSING_FAILED"
            db.commit()
    finally:
        db.close()
        _decrement_and_finalize(course_id)


def _decrement_and_finalize(course_id: str | None) -> None:
    if course_id is None:
        return
    finalize = False
    with _pool_lock:
        _course_inflight[course_id] -= 1
        if _course_inflight[course_id] <= 0:
            _course_inflight.pop(course_id, None)
            finalize = True

    if not finalize:
        return

    db: Session = SessionLocal()
    try:
        _finalize_course(db, course_id)
    except Exception:
        logger.exception("Course finalization failed for course_id=%s", course_id)
        db.rollback()
    finally:
        db.close()


def _finalize_course(db: Session, course_id: str) -> dict:
    """Build the canonical course KB once, then apply the READY contract."""
    course = db.get(models.Course, course_id)
    if course is None:
        return {"ready": False, "reason": "COURSE_NOT_FOUND"}

    # The builder consumes only persisted extracted_text. It never calls the
    # parser/OCR or the AI provider, and is intentionally course-level.
    build_course_knowledge_base(db, course_id, apply=True)
    readiness = evaluate_course_readiness(db, course_id)
    if readiness["ready"]:
        from app.services.scoring import score_study_units

        score_study_units(db, course)
        course.status = "READY"
    elif course.status not in {"ARCHIVED", "LEARNING"}:
        course.status = "ANALYZING"
    db.commit()
    return readiness


def enqueue_material(material_id: str) -> None:
    """Submit a material for async processing. Fire-and-forget."""
    db: Session = SessionLocal()
    try:
        material = db.get(models.Material, material_id)
        if material is not None:
            with _pool_lock:
                _course_inflight[material.course_id] += 1
    finally:
        db.close()
    _executor.submit(_run, material_id)
