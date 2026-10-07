import os
import re
import uuid
import hashlib
from datetime import datetime

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.errors import NotFoundError, InvalidRequestError

ALLOWED_EXT = {".txt", ".md", ".pdf", ".pptx", ".ppt", ".docx", ".doc"}
# Files that cannot be parsed textually are recorded but produce a readable
# placeholder so the course still becomes usable (graceful degradation).
PARSEABLE_EXT = {".txt", ".md", ".pdf"}
TEACHING_TYPES = {"TEXTBOOK", "TEACHER_PPT", "CLASS_NOTES"}
TYPE_CHANGE_REBUILD_ERROR = "TYPE_CHANGE_REBUILD_REQUIRED"

_PDF_MAGIC = b"%PDF-"
_MAX_PDF_SNIFF = 64 * 1024  # bytes read from tail when validating %%EOF


def validate_upload(file: UploadFile) -> None:
    """Reject unsupported types, oversized files, and clearly corrupted PDFs
    before they are persisted or queued for AI processing."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise InvalidRequestError(
            f"不支持的文件类型：{ext or '无扩展名'}（支持 txt / md / pdf / ppt / pptx / doc / docx）"
        )

    content = file.file.read()
    file.file.seek(0)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise InvalidRequestError(
            f"文件过大：{len(content) / 1024 / 1024:.1f}MB（上限 {settings.max_upload_mb}MB）"
        )

    if ext == ".pdf":
        _validate_pdf(content, filename)


def upload_file_hash(file: UploadFile) -> str:
    """Return the stable content hash without consuming the upload stream."""
    content = file.file.read()
    file.file.seek(0)
    return hashlib.sha256(content).hexdigest()


def _validate_pdf(content: bytes, filename: str) -> None:
    if not content:
        raise InvalidRequestError(f"PDF 文件为空：{filename}")
    if not content.startswith(_PDF_MAGIC):
        raise InvalidRequestError(f"文件不是有效的 PDF（缺少 %PDF 文件头）：{filename}")
    tail = content[-_MAX_PDF_SNIFF:]
    if b"%%EOF" not in tail:
        raise InvalidRequestError(f"PDF 文件可能已损坏（缺少 %%EOF 结束标记）：{filename}")


def create_material(
    db: Session,
    course: models.Course,
    material_type: str,
    file: UploadFile | None = None,
    url: str | None = None,
    upload_dir: str = "./data/materials",
    file_hash: str | None = None,
) -> models.Material:
    if not material_type:
        raise InvalidRequestError("Material type is required")

    name = (file.filename if file else url or "link").strip() or "material"
    material = models.Material(
        course_id=course.id,
        type=material_type,
        source="upload" if file else "url",
        name=name,
        external_url=url,
        status="PENDING",
        progress=0,
    )
    db.add(material)
    db.flush()

    if file:
        validate_upload(file)
        if file_hash is None:
            file_hash = upload_file_hash(file)
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(file.filename or "")[1].lower()
        safe = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(upload_dir, safe)
        content = file.file.read()
        with open(path, "wb") as f:
            f.write(content)
        material.file_path = path
        material.file_hash = file_hash

    db.add(
        models.Event(
            user_id=course.user_id,
            course_id=course.id,
            event_type="MATERIAL_UPLOADED",
            entity_type="material",
            entity_id=material.id,
        )
    )
    db.flush()
    return material


def change_material_type(
    db: Session,
    course: models.Course,
    material_id: str,
    new_type: str,
) -> dict:
    """Change only a material's classification and isolate stale derivatives.

    Parsing metadata and extracted text are intentionally untouched.  When an
    exam source stops being an exam, existing question links/evidence remain
    available for audit but are made inactive so practice and exam evidence do
    not silently use the old classification.  No parser, builder, or mapping
    job is scheduled here.
    """
    material = db.get(models.Material, material_id)
    if material is None or material.course_id != course.id:
        raise NotFoundError("Material not found")

    old_type = material.type
    if old_type == new_type:
        return {
            "changed": False,
            "old_type": old_type,
            "new_type": new_type,
            "rebuild_required": False,
            "deactivated_question_links": 0,
            "deactivated_exam_evidence": 0,
        }

    deactivated_question_links = 0
    deactivated_exam_evidence = 0
    if old_type == "REAL_EXAM" and new_type != "REAL_EXAM":
        question_ids = [
            row[0]
            for row in db.query(models.Question.id)
            .filter(models.Question.source_material_id == material.id)
            .all()
        ]
        if question_ids:
            links = (
                db.query(models.QuestionStudyUnit)
                .filter(models.QuestionStudyUnit.question_id.in_(question_ids))
                .all()
            )
            for link in links:
                if link.is_active is not False:
                    link.is_active = False
                    link.invalidated_reason = "MATERIAL_TYPE_CHANGED"
                    deactivated_question_links += 1

            evidences = (
                db.query(models.ExamEvidence)
                .filter(
                    models.ExamEvidence.source_material_id == material.id,
                    models.ExamEvidence.is_active.isnot(False),
                )
                .all()
            )
            for evidence in evidences:
                evidence.is_active = False
                evidence.invalidated_reason = "MATERIAL_TYPE_CHANGED"
                deactivated_exam_evidence += 1

    material.type = new_type
    material.error_code = TYPE_CHANGE_REBUILD_ERROR
    if course.status != "ARCHIVED":
        course.status = "ANALYZING"
    db.flush()
    return {
        "changed": True,
        "old_type": old_type,
        "new_type": new_type,
        "rebuild_required": True,
        "deactivated_question_links": deactivated_question_links,
        "deactivated_exam_evidence": deactivated_exam_evidence,
    }


def delete_material(db: Session, course: models.Course, material_id: str) -> str:
    """Delete a material and incrementally clean up derived course data.

    Per docs/04 "incremental update": removing a source only removes the Evidence
    it contributed, any StudyUnits/Questions that now have no other supporting
    evidence, and the mapping between them. Student mastery on surviving units is
    preserved, then importance is re-scored. The course is never fully re-analyzed.
    """
    from app.services.scoring import score_study_units

    material = db.get(models.Material, material_id)
    if material is None or material.course_id != course.id:
        raise NotFoundError("Material not found")

    mid = material.id
    evidence_ids = [ev.id for ev in material.evidences]

    # Remove the stored file, if any.
    if material.file_path:
        try:
            if os.path.exists(material.file_path):
                os.remove(material.file_path)
        except OSError:
            pass

    # Collect study units affected by this material's evidences.
    affected_unit_ids = set()
    if evidence_ids:
        links = (
            db.query(models.StudyUnitEvidence)
            .filter(models.StudyUnitEvidence.evidence_id.in_(evidence_ids))
            .all()
        )
        affected_unit_ids.update(link.study_unit_id for link in links)
        db.query(models.StudyUnitEvidence).filter(
            models.StudyUnitEvidence.evidence_id.in_(evidence_ids)
        ).delete(synchronize_session=False)

    # Units that no longer have any evidence are orphaned -> remove them and
    # their dependent records, but keep mastery of units with remaining evidence.
    orphaned_question_ids = set()
    for uid in affected_unit_ids:
        remaining = (
            db.query(models.StudyUnitEvidence)
            .filter(models.StudyUnitEvidence.study_unit_id == uid)
            .count()
        )
        if remaining:
            continue
        unit = db.get(models.StudyUnit, uid)
        if unit is None:
            continue
        orphaned_question_ids.update(ql.question_id for ql in unit.question_links)
        db.query(models.Recommendation).filter(models.Recommendation.study_unit_id == unit.id).delete(synchronize_session=False)
        db.query(models.LearningRecord).filter(models.LearningRecord.study_unit_id == unit.id).delete(synchronize_session=False)
        db.query(models.PracticeRecord).filter(models.PracticeRecord.study_unit_id == unit.id).delete(synchronize_session=False)
        db.query(models.LearningSession).filter(models.LearningSession.study_unit_id == unit.id).delete(synchronize_session=False)
        db.delete(unit)

    # Questions that no longer map to any unit are orphaned too.
    for qid in orphaned_question_ids:
        remaining = (
            db.query(models.QuestionStudyUnit)
            .filter(models.QuestionStudyUnit.question_id == qid)
            .count()
        )
        if remaining:
            continue
        db.query(models.PracticeRecord).filter(models.PracticeRecord.question_id == qid).delete(synchronize_session=False)
        question = db.get(models.Question, qid)
        if question is not None:
            db.delete(question)

    # Remove the evidences themselves, then the material row.
    for ev_id in evidence_ids:
        ev = db.get(models.Evidence, ev_id)
        if ev is not None:
            db.delete(ev)
    db.delete(material)
    db.flush()

    remaining_materials = (
        db.query(models.Material).filter(models.Material.course_id == course.id).count()
    )
    if remaining_materials == 0:
        course.status = "CREATED"
    elif course.status in ("READY", "LEARNING"):
        course.status = "READY"

    score_study_units(db, course)

    db.add(
        models.Event(
            user_id=course.user_id,
            course_id=course.id,
            event_type="MATERIAL_DELETED",
            entity_type="material",
            entity_id=mid,
        )
    )
    db.flush()
    return mid


def material_out(m: models.Material) -> dict:
    return {
        "id": m.id,
        "course_id": m.course_id,
        "type": m.type,
        "source": m.source,
        "name": m.name,
        "external_url": m.external_url,
        "status": m.status,
        "progress": m.progress,
        "error_code": m.error_code,
        "rebuild_required": getattr(m, "error_code", None) == TYPE_CHANGE_REBUILD_ERROR,
        "parsing_status": getattr(m, "parsing_status", None) or "PENDING",
        "parser_method": getattr(m, "parser_method", None),
        "parser_version": getattr(m, "parser_version", None),
        "extracted_char_count": getattr(m, "extracted_char_count", None),
        "extraction_quality": getattr(m, "extraction_quality", None),
        "extraction_error": getattr(m, "extraction_error", None),
        "file_hash": getattr(m, "file_hash", None),
        "extracted_text_sample": (getattr(m, "extracted_text", None) or "")[:200],
    }


def infer_existing_material_type(name: str, current_type: str, extracted_text: str = "") -> str:
    """Conservatively classify legacy rows only when they are still TEXTBOOK.

    New uploads keep the user-selected type.  This helper is intended only for
    the explicit legacy migration of rows that were all accidentally stored as
    TEXTBOOK.  Existing application vocabulary maps to the same product
    categories: REAL_EXAM=EXAM, TEACHER_PPT=PPT, CLASS_NOTES=NOTES,
    HOMEWORK=ASSIGNMENT.
    """
    if current_type not in {"TEXTBOOK", "CLASS_NOTES"}:
        return current_type
    lower = (name or "").lower()
    if re.search(r"期末|试卷|试题|真题|考试|exam|test", lower):
        return "REAL_EXAM"
    if current_type == "CLASS_NOTES":
        return current_type
    if re.search(r"课件|讲义|ppt|slides", lower):
        return "TEACHER_PPT"
    if re.search(r"笔记|复习重点|notes", lower):
        return "CLASS_NOTES"
    if re.search(r"作业|assignment|homework", lower):
        return "HOMEWORK"
    # Some legacy exam files used only a year/sequence name (for example
    # 数据库18.pdf).  Use strong exam-document structure from already parsed
    # text, without introducing an AI classifier or overriding non-TEXTBOOK
    # user-selected types.
    text = extracted_text or ""
    if re.search(r"选择题|选题|答案写在此处|考试日期|考试形式|试卷共|查询如下|SQL\s*语句", text):
        return "REAL_EXAM"
    return current_type
