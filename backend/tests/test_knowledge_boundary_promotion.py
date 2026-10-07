from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.services.knowledge_base import (
    build_course_knowledge_base,
    canonicalize_title,
    extract_teaching_candidates,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _boundary_text():
    return """Contents
4.4.5 Referential Integrity 158
5.3 Triggers 207
8.3.2 Boyce-Codd Normal Form 360
11.6 Static Hashing 536
11.7 Dynamic Hashing 542
14.6 Serializability 668
----- page 2 -----
----- page 158 -----
4.4.5 Referential Integrity
Referential integrity requires every foreign key value to match a referenced key.
It prevents invalid references between related relations.
----- page 207 -----
5.3 Triggers
A trigger is a statement that the system executes automatically when a specified event occurs.
Triggers support database programming and integrity enforcement.
5.3.1 Need for Triggers
This subsection explains why a trigger can be useful in a database system.
----- page 360 -----
8.3.2 Boyce-Codd Normal Form
A relation schema is in Boyce-Codd Normal Form when every determinant is a candidate key.
BCNF is a stronger normal form used in relational database design.
----- page 536 -----
11.6 Static Hashing
Static hashing organizes records into buckets using a hash function.
11.7 Dynamic Hashing
Dynamic hashing adapts buckets as the file grows.
Hash indices support direct access to records.
----- page 668 -----
14.6 Serializability
Serializability determines whether concurrent transaction schedules are correct.
The two-phase locking protocol is a technique that ensures serializability.
"""


def test_multilevel_headings_and_derived_domain_signals_are_discovered():
    result = extract_teaching_candidates(_boundary_text())
    names = {item["canonical_name"] for item in result["accepted"]}

    assert {
        "Boyce-Codd Normal Form",
        "Referential Integrity",
        "Serializability",
        "Two-Phase Locking",
        "Database Triggers",
        "Hashing and Hash Indexing",
    } <= names
    assert sum(name == "Hashing and Hash Indexing" for name in names) == 1
    assert "Static Hashing" not in names
    assert "Dynamic Hashing" not in names
    assert "Need for Triggers" not in names


def test_invalid_heading_depth_and_noise_are_rejected():
    result = extract_teaching_candidates(
        """Contents
1.1 Relational Model 1
1..2 Not A Section 2
1.2.3.4.5 Too Deep 3
----- page 10 -----
1.1 Relational Model
The relational model represents data using relations and tuples.
1.2.3.4.5 Random Database Fragment
This is an unconfirmed subsection fragment.
list as
needed is
query as follows
"""
    )
    names = {item["canonical_name"] for item in result["accepted"]}
    assert names == {"Relational Model"}
    assert any(item["reason"] == "unconfirmed-subsection" for item in result["trace"]["filtered"])
    assert canonicalize_title("list as") is None
    assert canonicalize_title("query as follows") is None
    assert canonicalize_title("Copyright and Publisher") is None


def test_domain_signal_variants_and_parent_specificity_remain_distinct():
    assert canonicalize_title("Serializability") == "Serializability"
    assert canonicalize_title("Two-Phase Locking") == "Two-Phase Locking"
    assert canonicalize_title("Triggers") == "Database Triggers"
    assert canonicalize_title("Static Hashing") == "Hashing and Hash Indexing"
    assert canonicalize_title("Dynamic Hashing") == "Hashing and Hash Indexing"
    assert canonicalize_title("Database Systems") is None
    assert canonicalize_title("Transaction") == "Transactions"
    assert canonicalize_title("Transaction Isolation") == "Transaction Isolation"
    assert canonicalize_title("Index") == "Index"
    assert canonicalize_title("B+ Tree Index") == "B+ Tree Index"
    assert canonicalize_title("Completely Unrelated Topic") is None


def test_promotions_persist_real_excerpt_display_and_parent_metadata_idempotently():
    db = _session()
    db.add(models.User(id="user1"))
    db.add(models.Course(id="course1", user_id="user1", name="Database Systems", status="CREATED"))
    material = models.Material(
        id="textbook1",
        course_id="course1",
        type="TEXTBOOK",
        source="upload",
        name="database-systems.pdf",
        status="COMPLETED",
        parsing_status="PARSED",
        extracted_text=_boundary_text(),
        extracted_char_count=len(_boundary_text()),
        extraction_quality="HIGH",
    )
    db.add(material)
    db.flush()
    parent = models.StudyUnit(
        id="parent1",
        course_id="course1",
        title="Normalization and Normal Forms",
        canonical_name="Normalization and Normal Forms",
        source_material_id="textbook1",
        source_type="TEXTBOOK",
        source_excerpt="Existing parent unit.",
        source_location="page 350",
    )
    db.add(parent)
    db.flush()

    first = build_course_knowledge_base(db, "course1", apply=True)
    db.commit()
    first_units = {
        unit.canonical_name: unit.id
        for unit in db.query(models.StudyUnit).filter_by(course_id="course1").all()
    }
    promoted = db.query(models.StudyUnit).filter(
        models.StudyUnit.canonical_name.in_([
            "Boyce-Codd Normal Form",
            "Referential Integrity",
            "Serializability",
            "Two-Phase Locking",
            "Database Triggers",
            "Hashing and Hash Indexing",
        ])
    ).all()

    assert first["deduplicated_count"] == 6
    assert len(promoted) == 6
    assert db.get(models.StudyUnit, "parent1").id == "parent1"
    assert db.query(models.StudyUnit).count() == 7
    assert db.query(models.StudyUnit).filter_by(title="Boyce-Codd Normal Form (BCNF)").count() == 1
    assert db.query(models.StudyUnit).filter_by(title="Two-Phase Locking (2PL)").count() == 1
    assert all(unit.source_material_id == "textbook1" for unit in promoted)
    assert all(unit.source_excerpt and len(unit.source_excerpt) > len(unit.title) + 20 for unit in promoted)
    assert all(unit.source_location for unit in promoted)

    second = build_course_knowledge_base(db, "course1", apply=True)
    db.commit()
    second_units = {
        unit.canonical_name: unit.id
        for unit in db.query(models.StudyUnit).filter_by(course_id="course1").all()
    }
    assert second["deduplicated_count"] == 6
    assert db.query(models.StudyUnit).count() == 7
    assert first_units == second_units
    db.close()
