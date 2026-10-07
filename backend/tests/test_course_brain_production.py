from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, worker
from app.database import Base
from app.services import course_brain
from app.services.knowledge_base import evaluate_course_readiness


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _course(db, status="ANALYZING"):
    db.add(models.User(id="user1"))
    db.add(models.Course(id="course1", user_id="user1", name="Database Systems", status=status))
    db.flush()


def _material(db, material_id, material_type="TEXTBOOK", *, parsing_status="PARSED", text="1.1 Relational Model\nThe relational model represents data using relations and tuples."):
    material = models.Material(
        id=material_id,
        course_id="course1",
        type=material_type,
        source="upload",
        name=f"{material_id}.pdf",
        status="COMPLETED",
        parsing_status=parsing_status,
        extracted_text=text,
        extracted_char_count=len(text) if text else 0,
        extraction_quality="HIGH" if parsing_status == "PARSED" else "LOW",
    )
    db.add(material)
    db.flush()
    return material


def test_teaching_processing_does_not_call_legacy_ai_or_create_units(monkeypatch):
    db = _session()
    _course(db)
    material = _material(db, "textbook1")
    monkeypatch.setattr(
        course_brain,
        "parse_material",
        lambda *args, **kwargs: {
            "text": material.extracted_text,
            "status": "PARSED",
            "quality": "HIGH",
            "method": "cached",
            "error": None,
            "cached": True,
        },
    )
    monkeypatch.setattr(
        course_brain.ai_service,
        "analyze_material",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy AI provider called")),
    )

    course_brain.process_material(db, material)

    assert material.status == "COMPLETED"
    assert db.query(models.StudyUnit).count() == 0
    db.close()


def test_valid_cached_teaching_material_builds_canonical_kb_and_ready(monkeypatch):
    db = _session()
    _course(db)
    _material(db, "textbook1")
    monkeypatch.setattr(course_brain, "parse_material", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parser called")))

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is True
    assert result["reason"] == "READY"
    assert db.get(models.Course, "course1").status == "READY"
    assert db.query(models.StudyUnit).filter(models.StudyUnit.canonical_name.isnot(None)).count() > 0
    db.close()


def test_failed_teaching_material_is_not_ready():
    db = _session()
    _course(db)
    _material(db, "failed", parsing_status="FAILED", text="")

    result = worker._finalize_course(db, "course1")

    assert result == {
        "ready": False,
        "reason": "NO_PARSED_TEACHING_MATERIAL",
        "eligible_teaching_material_count": 0,
        "study_unit_count": 0,
    }
    assert db.get(models.Course, "course1").status == "ANALYZING"
    db.close()


def test_parsed_teaching_material_with_zero_candidates_is_not_ready():
    db = _session()
    _course(db)
    _material(db, "plain", text="This is ordinary prose without a course heading.")

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is False
    assert result["reason"] == "NO_STUDY_UNITS"
    assert result["eligible_teaching_material_count"] == 1
    assert db.get(models.Course, "course1").status == "ANALYZING"
    db.close()


def test_only_real_exam_is_not_ready():
    db = _session()
    _course(db)
    _material(db, "exam", "REAL_EXAM", text="Question 1: explain transactions.")

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is False
    assert result["reason"] == "NO_TEACHING_MATERIAL"
    assert db.query(models.StudyUnit).count() == 0
    db.close()


def test_teaching_and_real_exam_ready_only_from_teaching_kb():
    db = _session()
    _course(db)
    _material(db, "textbook")
    _material(db, "exam", "REAL_EXAM", text="Question 1: explain transactions.")

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is True
    units = db.query(models.StudyUnit).all()
    assert units
    assert all(unit.source_type in {"TEXTBOOK", "TEACHER_PPT", "CLASS_NOTES"} for unit in units)
    db.close()


def test_one_valid_and_one_failed_teaching_material_can_be_ready():
    db = _session()
    _course(db)
    _material(db, "textbook")
    _material(db, "notes", "CLASS_NOTES", parsing_status="FAILED", text="")

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is True
    assert db.get(models.Material, "notes").parsing_status == "FAILED"
    db.close()


def test_low_quality_teaching_material_only_is_not_ready():
    db = _session()
    _course(db)
    _material(db, "low", parsing_status="LOW_QUALITY", text="short")

    result = worker._finalize_course(db, "course1")

    assert result["ready"] is False
    assert result["reason"] == "NO_PARSED_TEACHING_MATERIAL"
    db.close()


def test_repeated_finalization_is_idempotent():
    db = _session()
    _course(db)
    _material(db, "textbook")

    first = worker._finalize_course(db, "course1")
    units_after_first = db.query(models.StudyUnit).count()
    evidence_after_first = db.query(models.Evidence).count()
    second = worker._finalize_course(db, "course1")

    assert first["ready"] is True and second["ready"] is True
    assert db.query(models.StudyUnit).count() == units_after_first
    assert db.query(models.Evidence).count() == evidence_after_first
    db.close()


def test_readiness_evaluator_is_derived_and_does_not_mutate_state():
    db = _session()
    _course(db)
    _material(db, "textbook")

    before = db.get(models.Course, "course1").status
    result = evaluate_course_readiness(db, "course1")

    assert result["ready"] is False
    assert result["reason"] == "NO_STUDY_UNITS"
    assert db.get(models.Course, "course1").status == before
    db.close()
