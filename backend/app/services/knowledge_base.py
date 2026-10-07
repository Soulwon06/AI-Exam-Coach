"""Course Knowledge Base v1 built only from persisted teaching-material text.

This module intentionally does not import the material parser or AI provider.
Its input is ``Material.extracted_text`` already stored by P1-B.  Exam files
remain source material for a later mapping/frequency phase, not KB generators.
"""
from difflib import SequenceMatcher
import re
import unicodedata

from sqlalchemy.orm import Session

from app import models


CANONICAL_GRAPH_VERSION = "DATABASE_CANONICAL_GRAPH_V1"


TEACHING_TYPES = {"TEXTBOOK", "TEACHER_PPT", "CLASS_NOTES"}
MAX_KNOWLEDGE_POINTS = 80
_PAGE_MARKER = re.compile(r"^-+\s*page\s+(\d+)\s*-+$", re.IGNORECASE)
_SECTION = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,4})\s+(.+?)\s*$")
_CHAPTER = re.compile(r"^chapter\s+\d+\b", re.IGNORECASE)
_CHAPTER_TITLE = re.compile(r"^chapter\s+\d+\s+(.+?)\s*$", re.IGNORECASE)
_PAGE_SUFFIX = re.compile(r"\s+\d{1,4}\s*$")
_DOMAIN_SIGNAL = re.compile(
    r"\b(?:database|relational|relation|schema|sql|query|algebra|calculus|"
    r"key|constraint|normal|functional|dependenc(?:y|ies)|transactions?|concurr\w*|"
    r"lock(?:s|ed|ing)?|deadlock|serializ(?:ability|able|e|ed|ation|ations)|"
    r"recovery|index(?:es|ed|ing)?|hash(?:es|ed|ing)?|tree|join|view(?:s)?|"
    r"trigger(?:s|ed|ing)?|"
    r"procedure|authorization|storage|optimization|integrity|entity|model|views?)\b",
    re.IGNORECASE,
)
_EXCLUDED_TITLE = re.compile(
    r"^(?:summary|exercises?|bibliographical notes?|contents?|references?|"
    r"answers?|introduction|overview|database-system applications|database systems|"
    r"purpose of database systems|database users and administrators|history of database systems)$",
    re.IGNORECASE,
)
_BAD_TITLE = re.compile(
    r"(?:copyright|publisher|isbn|www\.|https?://|all rights reserved|"
    r"following|as follows|this section|example|exercise|bibliograph)",
    re.IGNORECASE,
)

# Only these six child boundaries are approved for promotion in the current
# MVP. Discovery may see other subsections, but they must not become units
# without an explicit human-confirmed definition here.
_BOUNDARY_PROMOTIONS = (
    {
        "canonical_name": "Boyce-Codd Normal Form",
        "display_title": "Boyce-Codd Normal Form (BCNF)",
        "aliases": ("BCNF", "Boyce-Codd Normal Form", "Boyce–Codd Normal Form"),
        "parent_context": "Normalization and Normal Forms",
        "promotion_reason": "independently examinable normal form with distinct mastery boundary",
    },
    {
        "canonical_name": "Referential Integrity",
        "display_title": "Referential Integrity",
        "aliases": ("Referential Integrity", "Referential Integrity Constraint"),
        "parent_context": "Integrity Constraints",
        "promotion_reason": "independently learnable and examinable integrity concept",
    },
    {
        "canonical_name": "Serializability",
        "display_title": "Serializability",
        "aliases": ("Serializability",),
        "parent_context": "Transaction Isolation / transaction concurrency",
        "promotion_reason": "distinct concurrency-control concept, not an isolation level",
    },
    {
        "canonical_name": "Two-Phase Locking",
        "display_title": "Two-Phase Locking (2PL)",
        "aliases": ("2PL", "Two Phase Locking", "Two-Phase Locking", "Two-Phase Locking Protocol"),
        "parent_context": "Lock-Based Protocols",
        "promotion_reason": "independently examinable locking protocol",
    },
    {
        "canonical_name": "Database Triggers",
        "display_title": "Database Triggers",
        "aliases": ("Trigger", "Triggers", "SQL Triggers", "Database Triggers"),
        "parent_context": "SQL/database programming",
        "promotion_reason": "independently defined SQL/database-programming concept",
    },
    {
        "canonical_name": "Hashing and Hash Indexing",
        "display_title": "Hashing and Hash Indexing",
        "aliases": ("Static Hashing", "Dynamic Hashing", "Hash Indexing", "Hash Indices", "Hashing and Hash Indexing"),
        "parent_context": "Indexing",
        "promotion_reason": "stable parent boundary for static and dynamic hashing evidence",
    },
)


def canonical_study_unit_query(db: Session, course_id: str):
    """Return the canonical teaching StudyUnits for a course.

    This is the same canonical classification used by the READY contract:
    canonical_name must be present and the unit must come from a teaching
    source. Legacy rows remain in the database but are not part of normal
    Course Brain product paths.
    """
    return db.query(models.StudyUnit).filter(
        models.StudyUnit.course_id == course_id,
        models.StudyUnit.canonical_name.isnot(None),
        models.StudyUnit.source_type.in_(TEACHING_TYPES),
    )


def get_canonical_study_unit(
    db: Session, study_unit_id: str, course_id: str | None = None
) -> models.StudyUnit | None:
    """Find one legacy teaching or canonical-graph StudyUnit by exact ID."""
    query = db.query(models.StudyUnit).filter(
        models.StudyUnit.id == study_unit_id,
        (models.StudyUnit.canonical_name.isnot(None) & models.StudyUnit.source_type.in_(TEACHING_TYPES))
        | (models.StudyUnit.canonical_graph_version == CANONICAL_GRAPH_VERSION),
    )
    if course_id is not None:
        query = query.filter(models.StudyUnit.course_id == course_id)
    return query.first()


# Specific aliases are deliberately ordered from narrow to broad.  This keeps
# Transaction and Transaction Isolation, and Index and B+ Tree Index, distinct.
_CANONICAL_RULES = (
    (r"b\s*\+\s*[- ]?\s*tree|b\s*\+\s*tree", "B+ Tree Index"),
    (r"functional[- ]dependency theory|functional dependencies?", "Functional Dependencies"),
    (r"first normal form", "First Normal Form"),
    (r"second normal form", "Second Normal Form"),
    (r"third normal form", "Third Normal Form"),
    (r"normal forms?", "Normalization and Normal Forms"),
    (r"tuple relational calculus", "Tuple Relational Calculus"),
    (r"domain relational calculus", "Domain Relational Calculus"),
    (r"relational algebra", "Relational Algebra"),
    (r"entity[- ]relationship model", "Entity-Relationship Model"),
    (r"^view of data$", "Data Abstraction"),
    (r"relational model", "Relational Model"),
    (r"relational database design", "Relational Database Design"),
    (r"integrity constraints?", "Integrity Constraints"),
    (r"concurrency control", "Concurrency Control"),
    (r"recovery system|database recovery", "Database Recovery"),
    (r"deadlock", "Deadlock"),
    (r"transaction isolation|isolation levels?", "Transaction Isolation"),
    (r"transaction management|^transactions?$", "Transactions"),
    (r"query optimization", "Query Optimization"),
    (r"query processing", "Query Processing"),
    (r"nested subqueries?", "Nested Subqueries"),
    (r"join expressions?|join operation", "Join"),
    (r"aggregate functions?", "Aggregate Functions"),
    (r"sql data definition", "SQL Data Definition"),
    (r"basic structure of sql queries|sql query language|introduction to sql", "SQL Queries"),
    (r"^views?$", "Views"),
    (r"functions? and procedures?|stored procedures?", "Stored Procedures and Functions"),
    (r"authorization", "Database Authorization"),
    (r"ordered indices?|ordered indexing", "Ordered Indexing"),
    (r"index definition in sql|indexing and hashing|index files?", "Indexing"),
    (r"database schema|schema diagrams?", "Database Schema"),
    (r"^keys?$", "Keys"),
    (r"relational operations?", "Relational Operations"),
)


def _normalise_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("ﬁ", "fi").replace("–", "-").replace("—", "-")
    value = re.sub(r"\*+$", "", value)
    value = _PAGE_SUFFIX.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" .:;,-")
    return value


def _boundary_key(value: str) -> str:
    """Normalize an approved boundary alias for exact, explainable matching."""
    value = _normalise_title(value).casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


def _boundary_definition(value: str) -> dict | None:
    key = _boundary_key(value)
    for definition in _BOUNDARY_PROMOTIONS:
        if key in {_boundary_key(alias) for alias in definition["aliases"]}:
            return definition
    return None


def _heading_depth(line: str) -> int | None:
    match = _SECTION.match(_normalise_title(line))
    if not match:
        return None
    return match.group(1).count(".") + 1


def _boundary_line_match(line: str, definition: dict) -> bool:
    line_key = _boundary_key(line)
    return any(_boundary_key(alias) in line_key for alias in definition["aliases"])


def _find_boundary_occurrence(
    lines: list[str], definition: dict, toc_limit: int
) -> tuple[int, str] | None:
    """Find a bounded body occurrence for an approved boundary.

    This fallback is needed for concepts such as Two-Phase Locking, which is
    explained in body prose rather than introduced by a clean standalone
    heading. It never promotes an unlisted term.
    """
    matches = [
        index for index, line in enumerate(lines)
        if index >= toc_limit and _boundary_line_match(line, definition)
    ]
    if not matches:
        return None

    for index in matches:
        header = _header_at(lines, index)
        if header is not None and _is_better_occurrence(lines, index):
            return index, header[0]

    # Prefer explanatory prose over an isolated mention or an exercise.
    for index in matches:
        line = lines[index].casefold()
        if any(marker in line for marker in ("requires", "protocol", "technique", "organizes")):
            return index, definition["display_title"]
    return matches[0], definition["display_title"]


def _boundary_excerpt(lines: list[str], index: int, display_title: str) -> str:
    parts = [display_title]
    for line in lines[index: index + 10]:
        value = line.strip()
        if not value or _PAGE_MARKER.match(value):
            continue
        if value.casefold() == display_title.casefold():
            continue
        parts.append(value)
        if len("\n".join(parts)) >= 420 or len(parts) >= 5:
            break
    return "\n".join(parts)[:600]


def canonicalize_title(title: str) -> str | None:
    value = _normalise_title(title)
    if not value or _EXCLUDED_TITLE.match(value) or _BAD_TITLE.search(value):
        return None
    if len(value) < 3 or len(value) > 80 or not _DOMAIN_SIGNAL.search(value):
        return None
    boundary = _boundary_definition(value)
    if boundary is not None:
        return boundary["canonical_name"]
    lower = value.casefold()
    for pattern, canonical in _CANONICAL_RULES:
        if re.search(pattern, lower, re.IGNORECASE):
            return canonical
    # A heading can be a valid course concept without a dedicated alias, but
    # reject sentence-like headings and generic chapter labels.
    if re.search(r"[.!?]$|\b(?:is|are|was|were|can|may|will)\b", lower):
        return None
    if len(value.split()) > 8:
        return None
    return value


def _candidate_excerpt(lines: list[str], index: int, heading: str) -> str:
    parts = [heading]
    for line in lines[index + 1: index + 12]:
        value = line.strip()
        if not value or _PAGE_MARKER.match(value):
            continue
        if _SECTION.match(value) or _CHAPTER.match(value):
            break
        if value.isdigit() or len(value) < 12:
            continue
        parts.append(value)
        if len("\n".join(parts)) >= 420:
            break
        if len(parts) >= 3:
            break
    return "\n".join(parts)[:600]


def _section_at(lines: list[str], index: int) -> tuple[str, str] | None:
    line = _normalise_title(lines[index])
    match = _SECTION.match(line)
    if not match:
        return None
    title = _normalise_title(match.group(2))
    # Contents wraps long titles onto the following line. Join only the
    # obvious continuation cases; body prose is never used to invent a title.
    if index + 1 < len(lines) and re.search(r"(?:of|and|using|functional|first normal|relational)$", title, re.IGNORECASE):
        following = _normalise_title(lines[index + 1])
        if following and not _SECTION.match(following) and not _CHAPTER.match(following) and not _PAGE_MARKER.match(following):
            title = _normalise_title(f"{title} {following}")
    return title, line


def _header_at(lines: list[str], index: int) -> tuple[str, str] | None:
    section = _section_at(lines, index)
    if section is not None:
        return section
    line = _normalise_title(lines[index])
    match = _CHAPTER_TITLE.match(line)
    if match:
        return _normalise_title(match.group(1)), line
    return None


def _source_location(lines: list[str], index: int) -> str | None:
    for line in reversed(lines[max(0, index - 80): index + 1]):
        match = _PAGE_MARKER.match(line.strip())
        if match:
            return f"page {match.group(1)}"
    return None


def _is_better_occurrence(lines: list[str], index: int) -> bool:
    # The table of contents appears near the front and usually has another
    # numbered entry immediately after it. Prefer an occurrence with prose.
    following = [line.strip() for line in lines[index + 1: index + 5] if line.strip()]
    if not following:
        return False
    if any(_PAGE_MARKER.match(line) for line in following):
        following = [line for line in following if not _PAGE_MARKER.match(line)]
    return bool(following and not _SECTION.match(following[0]))


def extract_teaching_candidates(text: str, max_candidates: int = MAX_KNOWLEDGE_POINTS) -> dict:
    """Extract numbered textbook section headings and grounded excerpts."""
    lines = (text or "").splitlines()
    raw = []
    filtered = []
    occurrences: dict[str, list[tuple[int, str]]] = {}
    # The first part of this textbook is its table of contents.  Whitelisting
    # titles seen there removes numbered exercises and question prompts from
    # the body while retaining the book's chapter/section structure.
    toc_titles: dict[str, set[str]] = {}
    has_contents = any(line.strip().casefold() == "contents" for line in lines[:200])
    if len(lines) >= 2000:
        toc_limit = 1200
    else:
        page_breaks = [i for i, line in enumerate(lines) if _PAGE_MARKER.match(line.strip())]
        toc_limit = (page_breaks[1] + 1) if len(page_breaks) >= 2 else max(1, (len(lines) + 1) // 3)
    for index in range(min(toc_limit, len(lines)) if has_contents else 0):
        header = _header_at(lines, index)
        if header is None:
            continue
        title, _ = header
        canonical = canonicalize_title(title)
        if canonical:
            toc_titles.setdefault(canonical, set()).add(re.sub(r"\s+", "", title).casefold())
    for index, raw_line in enumerate(lines):
        header = _header_at(lines, index)
        if header is None:
            continue
        title, line = header
        raw.append({"title": title, "line": index})
        canonical = canonicalize_title(title)
        if canonical is None:
            filtered.append({"candidate": title[:120], "reason": "low-quality-or-non-concept", "line": index})
            continue
        boundary = _boundary_definition(title)
        if (_heading_depth(line) or 0) > 2 and boundary is None:
            filtered.append({"candidate": title[:120], "reason": "unconfirmed-subsection", "line": index})
            continue
        title_key = re.sub(r"\s+", "", title).casefold()
        if toc_titles and (index < toc_limit or title_key not in toc_titles.get(canonical, set())):
            filtered.append({"candidate": title[:120], "reason": "not-a-structural-heading", "line": index})
            continue
        occurrences.setdefault(canonical, []).append((index, title))

    candidates = []
    discovered_boundaries: set[str] = set()
    for canonical, positions in occurrences.items():
        boundary = _boundary_definition(canonical)
        preferred = _find_boundary_occurrence(lines, boundary, toc_limit) if boundary else None
        if preferred is not None:
            index, title = preferred
            display_title = boundary["display_title"]
            excerpt = _boundary_excerpt(lines, index, display_title)
            discovered_boundaries.add(canonical)
        else:
            # Prefer a later body occurrence with explanatory prose over TOC.
            index, title = next(
                ((i, t) for i, t in reversed(positions) if _is_better_occurrence(lines, i)),
                positions[0],
            )
            display_title = title
            excerpt = _candidate_excerpt(lines, index, title)
        if len(excerpt) <= len(display_title) + 20:
            filtered.append({"candidate": display_title[:120], "reason": "missing-grounding-excerpt", "line": index})
            continue
        item = {
            "candidate": title,
            "canonical_name": canonical,
            "display_title": display_title,
            "source_excerpt": excerpt,
            "source_location": _source_location(lines, index),
            "line": index,
        }
        if boundary:
            item.update({
                "parent_context": boundary["parent_context"],
                "promotion_reason": boundary["promotion_reason"],
            })
        candidates.append(item)

    # A confirmed boundary may be expressed only in body prose rather than a
    # clean numbered heading (notably Two-Phase Locking).  Discovery remains
    # generic, while this explicit list is the only promotion path.
    for boundary in _BOUNDARY_PROMOTIONS:
        canonical = boundary["canonical_name"]
        if canonical in discovered_boundaries or any(
            item["canonical_name"] == canonical for item in candidates
        ):
            continue
        occurrence = _find_boundary_occurrence(lines, boundary, toc_limit)
        if occurrence is None:
            continue
        index, _ = occurrence
        display_title = boundary["display_title"]
        excerpt = _boundary_excerpt(lines, index, display_title)
        if len(excerpt) <= len(display_title) + 20:
            filtered.append({"candidate": display_title[:120], "reason": "missing-grounding-excerpt", "line": index})
            continue
        candidates.append({
            "candidate": display_title,
            "canonical_name": canonical,
            "display_title": display_title,
            "parent_context": boundary["parent_context"],
            "promotion_reason": boundary["promotion_reason"],
            "source_excerpt": excerpt,
            "source_location": _source_location(lines, index),
            "line": index,
        })
    candidates.sort(key=lambda item: item["line"])

    accepted = []
    for item in candidates:
        if any(
            item["canonical_name"] == old["canonical_name"]
            or (len(item["canonical_name"]) >= 8 and len(old["canonical_name"]) >= 8
                and SequenceMatcher(None, item["canonical_name"].casefold(), old["canonical_name"].casefold()).ratio() >= 0.93)
            for old in accepted
        ):
            filtered.append({"candidate": item["candidate"], "reason": "duplicate-or-near-duplicate", "line": item["line"]})
            continue
        accepted.append(item)

    if len(accepted) > max_candidates:
        accepted = accepted[:max_candidates]
        accepted_keys = {item["canonical_name"] for item in accepted}
        # Confirmed boundaries retain a slot if the generic candidate cap is
        # reached. This does not change discovery or canonicalization rules.
        for item in candidates:
            if not item.get("promotion_reason") or item["canonical_name"] in accepted_keys:
                continue
            evicted = next((old for old in reversed(accepted) if not old.get("promotion_reason")), None)
            if evicted is None:
                filtered.append({"candidate": item["candidate"], "reason": "max-candidates", "line": item["line"]})
                continue
            accepted.remove(evicted)
            accepted_keys.remove(evicted["canonical_name"])
            accepted.append(item)
            accepted_keys.add(item["canonical_name"])
        accepted.sort(key=lambda item: item["line"])

    return {
        "raw_candidate_count": len(raw),
        "normalised_candidate_count": len(candidates),
        "filtered_candidate_count": len(filtered),
        "candidates": candidates,
        "accepted": accepted,
        "trace": {
            "source_excerpt_sample": [item["source_excerpt"][:500] for item in accepted[:20]],
            "candidates": [{k: item[k] for k in ("candidate", "canonical_name", "source_location")} for item in candidates[:200]],
            "filtered": filtered[:200],
            "accepted": [{k: item[k] for k in ("candidate", "canonical_name", "source_location")} for item in accepted],
        },
    }


def _teaching_evidence_type(material_type: str) -> str:
    return {"TEXTBOOK": "TEXTBOOK_CONTENT", "TEACHER_PPT": "TEACHER_EMPHASIS", "CLASS_NOTES": "CLASS_NOTE"}.get(material_type, "TEXTBOOK_CONTENT")


def evaluate_course_readiness(db: Session, course_id: str) -> dict:
    """Evaluate the derived READY contract without changing database state.

    Readiness is intentionally based on canonical teaching units, not on a
    worker's generic COMPLETED flag or on exam-only questions.
    """
    teaching_materials = (
        db.query(models.Material)
        .filter(
            models.Material.course_id == course_id,
            models.Material.type.in_(TEACHING_TYPES),
        )
        .all()
    )
    eligible_materials = [
        material
        for material in teaching_materials
        if material.parsing_status == "PARSED" and (material.extracted_text or "").strip()
    ]
    study_unit_count = canonical_study_unit_query(db, course_id).count()
    if not teaching_materials:
        reason = "NO_TEACHING_MATERIAL"
    elif not eligible_materials:
        reason = "NO_PARSED_TEACHING_MATERIAL"
    elif study_unit_count == 0:
        reason = "NO_STUDY_UNITS"
    else:
        reason = "READY"
    return {
        "ready": reason == "READY",
        "reason": reason,
        "eligible_teaching_material_count": len(eligible_materials),
        "study_unit_count": study_unit_count,
    }


def build_course_knowledge_base(db: Session, course_id: str, apply: bool = True) -> dict:
    """Build teaching-source units from cached text only.

    ``apply=False`` is a dry run used by tests. No parsing, OCR, AI provider,
    question creation, importance scoring, or exam mapping occurs here.
    """
    materials = (
        db.query(models.Material)
        .filter(
            models.Material.course_id == course_id,
            models.Material.type.in_(TEACHING_TYPES),
        )
        .order_by(models.Material.created_at.asc())
        .all()
    )
    all_candidates = []
    skipped = []
    raw_candidate_count = 0
    normalised_candidate_count = 0
    material_traces = []
    for material in materials:
        if material.parsing_status != "PARSED" or not material.extracted_text:
            skipped.append({"material_id": material.id, "name": material.name, "reason": "no PARSED extracted_text"})
            continue
        result = extract_teaching_candidates(material.extracted_text)
        raw_candidate_count += result["raw_candidate_count"]
        normalised_candidate_count += result["normalised_candidate_count"]
        material_traces.append({
            "material_id": material.id,
            "material_name": material.name,
            "raw_candidate_count": result["raw_candidate_count"],
            "normalised_candidate_count": result["normalised_candidate_count"],
            "filtered": result["trace"]["filtered"][:50],
        })
        for item in result["accepted"]:
            item = dict(item)
            item.update({
                "material_id": material.id,
                "source_type": material.type,
                "material_name": material.name,
            })
            all_candidates.append(item)

    # Deduplicate across teaching materials, preserving the first grounded
    # occurrence. Exams never enter this collection.
    final = []
    filtered = []
    for item in all_candidates:
        duplicate = next((old for old in final if old["canonical_name"] == item["canonical_name"]), None)
        if duplicate:
            filtered.append({"candidate": item["candidate"], "canonical_name": item["canonical_name"], "reason": "cross-material-duplicate"})
            continue
        final.append(item)
        if len(final) >= MAX_KNOWLEDGE_POINTS:
            break

    if apply and final:
        course = db.get(models.Course, course_id)
        domain = (
            db.query(models.KnowledgeDomain)
            .filter_by(course_id=course_id, title=f"{course.name} · 课程知识库")
            .first()
        )
        if domain is None:
            domain = models.KnowledgeDomain(course_id=course_id, title=f"{course.name} · 课程知识库")
            db.add(domain)
            db.flush()
        for item in final:
            existing = (
                db.query(models.StudyUnit)
                .filter_by(course_id=course_id, canonical_name=item["canonical_name"])
                .first()
            )
            if existing is not None:
                continue
            metadata = {
                "knowledge_title": item["canonical_name"],
                "kind": "course_knowledge_base",
            }
            if item.get("parent_context"):
                metadata["parent_context"] = item["parent_context"]
            if item.get("promotion_reason"):
                metadata["promotion_reason"] = item["promotion_reason"]
            unit = models.StudyUnit(
                course_id=course_id,
                domain_id=domain.id,
                title=item.get("display_title", item["canonical_name"]),
                canonical_name=item["canonical_name"],
                source_material_id=item["material_id"],
                source_type=item["source_type"],
                source_excerpt=item["source_excerpt"],
                source_location=item["source_location"],
                description=None,
                importance_score=0.0,
                difficulty_score=0.0,
                importance_label=None,
                mastery_status="UNKNOWN",
                coverage_status="NOT_STARTED",
                progress=0,
                estimated_minutes=10,
            )
            db.add(unit)
            db.flush()
            evidence = models.Evidence(
                material_id=item["material_id"],
                evidence_type=_teaching_evidence_type(item["source_type"]),
                content_reference=item["source_excerpt"][:3000],
                metadata_=metadata,
            )
            db.add(evidence)
            db.flush()
            db.add(models.StudyUnitEvidence(study_unit_id=unit.id, evidence_id=evidence.id, relevance_score=1.0))

    if apply:
        db.flush()
    return {
        "teaching_material_count": len(materials),
        "skipped_materials": skipped,
        "raw_candidate_count": raw_candidate_count,
        "normalised_candidate_count": normalised_candidate_count,
        "deduplicated_count": len(final),
        "filtered_candidates": filtered,
        "knowledge_points": final,
        "trace": {
            "materials": material_traces,
            "accepted": [{k: item[k] for k in ("candidate", "canonical_name", "material_id", "source_location")} for item in final],
            "filtered": filtered[:200],
        },
    }
