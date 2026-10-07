"""D5-I-D-B contracts for source-grounded learning explanations."""

from types import SimpleNamespace

import pytest

from app import models
from app.routers import learning
from app.services import student_learning_model as slm


def _unit(kp_id: str | None = "kp-evidence"):
    return SimpleNamespace(
        canonical_graph_version=slm.CANONICAL_GRAPH_VERSION if kp_id else None,
        canonical_kp_id=kp_id,
        title="GROUP BY",
        estimated_minutes=10,
    )


def _packet(*, explanation=None, structure=None, status="EXACT_BLOCK"):
    return {
        "evidence_status": status,
        "explanation_evidence": explanation or [],
        "structure_evidence": structure or [],
    }


def _entry(text: str, location: str = "lines 1-1"):
    return {
        "source_file": "数据库系统概念_完整中文版.docx",
        "location": location,
        "excerpt": text,
        "match_method": "TIER_1_EXPLICIT_KNOWLEDGE_BLOCK",
        "excerpt_hash": "hash",
    }


def test_explanation_evidence_projection_is_bounded_and_provenanced(monkeypatch):
    long_text = "正文证据 " + ("x" * 500)
    monkeypatch.setattr(slm, "_EVIDENCE", {"kp-evidence": _packet(explanation=[_entry(long_text)])})

    result = slm.explanation_projection(_unit())

    assert result["explanation_mode"] == slm.EXPLANATION_EVIDENCE
    assert result["evidence_status"] == "EXACT_BLOCK"
    assert len(result["evidence_items"]) == 1
    assert len(result["evidence_items"][0]["excerpt"]) <= slm.MAX_EXPLANATION_EXCERPT_CHARS
    assert result["sources"][0]["source_file"] == "数据库系统概念_完整中文版.docx"
    assert result["sources"][0]["location"] == "lines 1-1"


def test_structure_only_projection_does_not_promote_structure_to_explanation(monkeypatch):
    monkeypatch.setattr(slm, "_EVIDENCE", {
        "kp-structure": _packet(
            structure=[_entry("章节目录片段", "line 20")],
            status="STRUCTURE_ONLY",
        )
    })

    result = slm.explanation_projection(_unit("kp-structure"))

    assert result["explanation_mode"] == slm.STRUCTURE_ONLY
    assert result["evidence_status"] == "STRUCTURE_ONLY"
    assert result["evidence_items"][0]["excerpt"] == "章节目录片段"


def test_missing_packet_uses_explicit_generic_fallback(monkeypatch):
    monkeypatch.setattr(slm, "_EVIDENCE", {})

    result = slm.explanation_projection(_unit("kp-missing"))

    assert result == {
        "explanation_mode": slm.GENERIC_FALLBACK,
        "evidence_status": "NO_EVIDENCE",
        "evidence_items": [],
        "sources": [],
    }


def test_non_graph_projection_keeps_legacy_unit_out_of_canonical_shadow(monkeypatch):
    monkeypatch.setattr(slm, "_EVIDENCE", {"legacy-kp": _packet(explanation=[_entry("must not leak")])})

    result = slm.explanation_projection(_unit(None))

    assert result["explanation_mode"] == slm.GENERIC_FALLBACK
    assert result["evidence_items"] == []
    assert result["sources"] == []


def test_learning_router_returns_structured_projection_fields(db, monkeypatch):
    user = models.User(id="explanation-user")
    course = models.Course(id="explanation-course", user_id=user.id, name="数据库系统", status="READY")
    unit = models.StudyUnit(
        id="explanation-unit",
        course_id=course.id,
        title="GROUP BY",
        canonical_name="GROUP BY",
        canonical_kp_id="kp-router",
        canonical_graph_version=slm.CANONICAL_GRAPH_VERSION,
        source_type="TEXTBOOK",
    )
    session = models.LearningSession(
        id="explanation-session",
        user_id=user.id,
        course_id=course.id,
        study_unit_id=unit.id,
        current_state="EXPLANATION",
    )
    db.add_all([user, course, unit, session])
    db.flush()
    monkeypatch.setattr(slm, "_EVIDENCE", {"kp-router": _packet(explanation=[_entry("GROUP BY groups rows")])})

    result = learning.get_explanation(session.id, db, user)["data"]

    assert result["explanation_mode"] == slm.EXPLANATION_EVIDENCE
    assert result["evidence_status"] == "EXACT_BLOCK"
    assert result["evidence_items"][0]["excerpt"] == "GROUP BY groups rows"
    assert "GROUP BY groups rows" in result["content"]


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()
    engine.dispose()
