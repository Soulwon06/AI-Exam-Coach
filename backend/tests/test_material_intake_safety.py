from io import BytesIO

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.routers import materials as materials_router
from app.services.material_service import change_material_type


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)(), engine


def _course(db):
    user = models.User(id="intake-user")
    course = models.Course(id="intake-course", user_id=user.id, name="Intake Course")
    db.add_all([user, course])
    db.flush()
    return user, course


def test_type_change_preserves_parsing_metadata_and_isolates_exam_derivatives():
    db, engine = _db()
    try:
        user, course = _course(db)
        material = models.Material(
            id="exam-material",
            course_id=course.id,
            type="REAL_EXAM",
            source="upload",
            name="exam.txt",
            status="COMPLETED",
            parsing_status="PARSED",
            parser_method="text",
            parser_version="material-parser-v1",
            extracted_text="cached exam text",
            extracted_char_count=17,
            extraction_quality="HIGH",
            file_hash="a" * 64,
        )
        unit = models.StudyUnit(
            id="intake-unit",
            course_id=course.id,
            title="Unit",
            canonical_name="Unit",
            source_type="TEXTBOOK",
        )
        question = models.Question(
            id="intake-question",
            course_id=course.id,
            source_material_id=material.id,
            type="SHORT_ANSWER",
            content="Question",
            answer="Answer",
        )
        link = models.QuestionStudyUnit(
            question_id=question.id,
            study_unit_id=unit.id,
            is_primary=True,
            is_active=True,
        )
        evidence = models.ExamEvidence(
            id="intake-evidence",
            question_id=question.id,
            source_material_id=material.id,
            study_unit_id=unit.id,
            is_primary=True,
            is_active=True,
        )
        db.add_all([material, unit, question, link, evidence])
        db.commit()

        before = {
            key: getattr(material, key)
            for key in (
                "extracted_text", "extracted_char_count", "parser_method",
                "parser_version", "extraction_quality", "file_hash",
            )
        }
        result = change_material_type(db, course, material.id, "TEXTBOOK")
        db.commit()

        assert result["rebuild_required"] is True
        assert material.type == "TEXTBOOK"
        assert {key: getattr(material, key) for key in before} == before
        assert link.is_active is False
        assert link.invalidated_reason == "MATERIAL_TYPE_CHANGED"
        assert evidence.is_active is False
        assert evidence.invalidated_reason == "MATERIAL_TYPE_CHANGED"
        assert db.get(models.Question, question.id) is not None
        assert material.error_code == "TYPE_CHANGE_REBUILD_REQUIRED"
        assert course.status == "ANALYZING"
        assert user.id == course.user_id
    finally:
        db.close()
        engine.dispose()


def test_upload_same_course_hash_reuses_existing_material_without_enqueue(monkeypatch, tmp_path):
    db, engine = _db()
    try:
        _, course = _course(db)
        enqueued = []
        monkeypatch.setattr(materials_router, "enqueue_material", enqueued.append)
        monkeypatch.setattr(materials_router.os, "getcwd", lambda: str(tmp_path))
        payload = b"small fixture material"

        first = materials_router.upload_material(
            course.id,
            UploadFile(BytesIO(payload), filename="fixture.txt"),
            type="TEXTBOOK",
            db=db,
            user=db.get(models.User, "intake-user"),
        )
        first_id = first["data"]["id"]
        assert first["data"]["upload_status"] == "UPLOADED"
        assert len(enqueued) == 1

        # The route accepts an upload_dir through create_material's default;
        # this test only verifies the persisted hash and reuse branch.
        second = materials_router.upload_material(
            course.id,
            UploadFile(BytesIO(payload), filename="renamed-fixture.txt"),
            type="REAL_EXAM",
            db=db,
            user=db.get(models.User, "intake-user"),
        )
        assert second["data"]["id"] == first_id
        assert second["data"]["upload_status"] == "REUSED"
        assert second["data"]["duplicate"] is True
        assert len(enqueued) == 1
        assert db.query(models.Material).filter_by(course_id=course.id).count() == 1
        assert db.get(models.Material, first_id).file_hash
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_type_change_same_type_is_a_noop():
    db, engine = _db()
    try:
        _, course = _course(db)
        material = models.Material(
            id="same-type-material", course_id=course.id, type="TEXTBOOK",
            source="upload", name="book.txt", error_code=None,
        )
        db.add(material)
        db.commit()
        result = change_material_type(db, course, material.id, "TEXTBOOK")
        assert result["changed"] is False
        assert material.error_code is None
    finally:
        db.close()
        engine.dispose()
