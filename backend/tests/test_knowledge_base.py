from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.services.knowledge_base import (
    build_course_knowledge_base,
    canonicalize_title,
    extract_teaching_candidates,
)


def test_teaching_heading_extraction_filters_noise_and_keeps_excerpt():
    text = """----- page 1 -----
Contents
1.1 Relational Model 1
1.2 Copyright and Publisher 2
1.2 SQL Data Definition 3
----- page 8 -----
1.1 Relational Model
The relational model represents data using relations, tuples, and attributes.
1.2 SQL Data Definition
SQL data definition statements create and modify database schemas.
1.3 query as follows
This is a sentence fragment and must not become a unit.
"""
    result = extract_teaching_candidates(text)
    names = [item["canonical_name"] for item in result["accepted"]]
    assert names == ["Relational Model", "SQL Data Definition"]
    assert "relational model represents" in result["accepted"][0]["source_excerpt"].lower()
    assert any(item["reason"] == "low-quality-or-non-concept" for item in result["trace"]["filtered"])


def test_canonicalization_keeps_parent_and_specific_concepts_distinct():
    assert canonicalize_title("B +-Tree Index Files") == "B+ Tree Index"
    assert canonicalize_title("B+ Tree Indexing") == "B+ Tree Index"
    assert canonicalize_title("Transactions") == "Transactions"
    assert canonicalize_title("Transaction Isolation") == "Transaction Isolation"
    assert canonicalize_title("Indexing and Hashing") == "Indexing"
    assert canonicalize_title("Database Systems") is None
    assert canonicalize_title("View of Data") == "Data Abstraction"
    assert canonicalize_title("Views") == "Views"
    assert canonicalize_title("Long-Duration Transactions") == "Long-Duration Transactions"


def test_course_kb_uses_cached_text_only_and_persists_source_fields(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.User(id="user1"))
    session.add(models.Course(id="course1", user_id="user1", name="数据库系统", status="CREATED"))
    session.add(models.Material(
        id="material1", course_id="course1", type="TEXTBOOK", source="upload",
        name="textbook.pdf", parsing_status="PARSED", extracted_text=(
            "----- page 10 -----\n"
            "3.1 Relational Model\n"
            "The relational model represents data using relations and tuples.\n"
            "3.2 Transaction Isolation\n"
            "Transaction isolation controls the visibility of concurrent changes.\n"
        ), extracted_char_count=230,
    ))
    session.flush()

    def fail_if_parser_called(*args, **kwargs):
        raise AssertionError("material parser must not run during KB generation")

    import app.services.course_brain as course_brain
    monkeypatch.setattr(course_brain, "parse_material", fail_if_parser_called)
    result = build_course_knowledge_base(session, "course1", apply=True)
    assert result["raw_candidate_count"] == 2
    assert result["deduplicated_count"] == 2
    units = session.query(models.StudyUnit).filter_by(course_id="course1").all()
    assert {u.canonical_name for u in units} == {"Relational Model", "Transaction Isolation"}
    assert all(u.source_material_id == "material1" for u in units)
    assert all(u.source_type == "TEXTBOOK" and u.source_excerpt for u in units)
    assert all(u.source_location == "page 10" for u in units)
    session.close()
