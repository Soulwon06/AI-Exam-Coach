"""Unified, read-only student-facing learning model.

The teaching knowledge base remains a separate legacy pipeline.  This module
selects the canonical graph population only for courses which have the frozen
graph materialization and decorates those rows with the frozen ranking and
hierarchy metadata.  It deliberately never builds, maps, or writes graph data.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.services.knowledge_base import CANONICAL_GRAPH_VERSION, canonical_study_unit_query
from app.services.question_trust import is_practice_trust_ready, trusted_explanation


ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = ROOT / "evaluation" / "datasets" / "database_canonical_knowledge_proposal.json"
EVIDENCE_PATH = ROOT / "evaluation" / "datasets" / "database_canonical_content_evidence_shadow.json"

EXPLANATION_EVIDENCE = "EXPLANATION_EVIDENCE"
STRUCTURE_ONLY = "STRUCTURE_ONLY"
GENERIC_FALLBACK = "GENERIC_FALLBACK"
MAX_EXPLANATION_EVIDENCE_ITEMS = 3
MAX_EXPLANATION_EXCERPT_CHARS = 360

_PROPOSAL: dict[str, dict[str, Any]] | None = None
_EVIDENCE: dict[str, dict[str, Any]] | None = None


def _load_proposal() -> dict[str, dict[str, Any]]:
    global _PROPOSAL
    if _PROPOSAL is None:
        payload = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
        _PROPOSAL = {row["canonical_candidate_id"]: row for row in payload.get("canonical_nodes", [])}
    return _PROPOSAL


def _load_evidence() -> dict[str, dict[str, Any]]:
    global _EVIDENCE
    if _EVIDENCE is None:
        payload = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        _EVIDENCE = {row["canonical_candidate_id"]: row for row in payload.get("packets", [])}
    return _EVIDENCE


def is_graph_course(db: Session, course_id: str) -> bool:
    return db.query(models.StudyUnit.id).filter(
        models.StudyUnit.course_id == course_id,
        models.StudyUnit.canonical_graph_version == CANONICAL_GRAPH_VERSION,
    ).first() is not None


def population_mode(db: Session, course_id: str) -> str:
    return "CANONICAL_GRAPH" if is_graph_course(db, course_id) else "LEGACY_TEACHING"


def _latest_learning_records(db: Session, user_id: str, study_unit_id: str) -> list[models.LearningRecord]:
    return (
        db.query(models.LearningRecord)
        .filter(
            models.LearningRecord.user_id == user_id,
            models.LearningRecord.study_unit_id == study_unit_id,
        )
        .order_by(models.LearningRecord.created_at.desc(), models.LearningRecord.id.desc())
        .all()
    )


def _student_preference(records: list[models.LearningRecord]) -> str:
    if records and records[0].event_type == "SKIPPED":
        return "DEFERRED"
    return "ACTIVE"


def _self_assessed(records: list[models.LearningRecord]) -> bool:
    return any(
        record.event_type == "MASTERED"
        and isinstance(record.metadata_, dict)
        and record.metadata_.get("source") == "SELF_ASSESSED"
        for record in records
    )


def _hierarchy(kp_id: str, unit: models.StudyUnit) -> dict[str, Any]:
    node = _load_proposal().get(kp_id, {})
    path = [part for part in str(node.get("structural_path") or "").split("/") if part]
    if not path:
        path = [unit.title]
    return {
        "canonical_id": kp_id,
        "node_role": node.get("node_role", "KNOWLEDGE_POINT"),
        "parent_canonical_id": node.get("parent_canonical_id"),
        "depth": node.get("depth", max(0, len(path) - 1)),
        "order": node.get("order", 0),
        "structural_path": path,
        "name_cn": node.get("name_cn"),
        "name_en": node.get("name_en"),
        "aliases": list(node.get("aliases") or []),
    }


def _evidence_provenance(kp_id: str) -> list[dict[str, Any]]:
    packet = _load_evidence().get(kp_id)
    if not packet:
        return []
    entries = [*packet.get("structure_evidence", []), *packet.get("explanation_evidence", [])]
    return [
        {
            "source_file": entry.get("source_file"),
            "location": entry.get("location"),
            "excerpt_hash": entry.get("excerpt_hash"),
            "match_method": entry.get("match_method"),
            "evidence_status": packet.get("evidence_status"),
        }
        for entry in entries
        if entry.get("source_file") and entry.get("location")
    ][:10]


def _bounded_excerpt(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_EXPLANATION_EXCERPT_CHARS:
        return text
    return text[: MAX_EXPLANATION_EXCERPT_CHARS - 1].rstrip() + "…"


def _project_evidence_entries(entries: Any) -> list[dict[str, Any]]:
    """Expose only bounded, persisted evidence; never generate explanation text."""

    projected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        source_file = str(entry.get("source_file") or "").strip()
        location = str(entry.get("location") or "").strip()
        excerpt = _bounded_excerpt(entry.get("excerpt") or entry.get("primary_text"))
        if not source_file or not location or not excerpt:
            continue
        key = (source_file, location, excerpt)
        if key in seen:
            continue
        seen.add(key)
        projected.append(
            {
                "excerpt": excerpt,
                "source_file": source_file,
                "display_label": _student_source_label(source_file),
                "location": location,
                "match_method": entry.get("match_method"),
                "excerpt_hash": entry.get("excerpt_hash"),
            }
        )
        if len(projected) >= MAX_EXPLANATION_EVIDENCE_ITEMS:
            break
    return projected


def _student_source_label(source_file: Any) -> str:
    """Return a safe student-facing label without exposing audit coordinates."""

    label = Path(str(source_file or "")).name.strip()
    if not label or re.search(r"(?:hash|block)[:=_]|\b[0-9a-f]{24,}\b", label, re.I):
        return "课程资料"
    return label.replace("_", " ")


def explanation_projection(unit: models.StudyUnit) -> dict[str, Any]:
    """Project frozen canonical evidence into a bounded student explanation.

    The projection is deliberately honest about the evidence tier: structure
    occurrences locate a source but do not become teaching prose, and missing
    packets use an explicit fallback state.
    """

    if unit.canonical_graph_version != CANONICAL_GRAPH_VERSION or not unit.canonical_kp_id:
        return {
            "explanation_mode": GENERIC_FALLBACK,
            "evidence_status": "NO_EVIDENCE",
            "evidence_items": [],
            "sources": [],
        }

    packet = _load_evidence().get(unit.canonical_kp_id)
    if not packet:
        return {
            "explanation_mode": GENERIC_FALLBACK,
            "evidence_status": "NO_EVIDENCE",
            "evidence_items": [],
            "sources": [],
        }

    explanation_items = _project_evidence_entries(packet.get("explanation_evidence"))
    structure_items = _project_evidence_entries(packet.get("structure_evidence"))
    if explanation_items:
        mode = EXPLANATION_EVIDENCE
        items = explanation_items
    elif structure_items:
        mode = STRUCTURE_ONLY
        items = structure_items
    else:
        mode = GENERIC_FALLBACK
        items = []

    sources = [
        {
            "type": "CANONICAL_EVIDENCE",
            "location": item["location"],
            "source_file": item["source_file"],
            "display_label": _student_source_label(item["source_file"]),
            "evidence_status": packet.get("evidence_status"),
        }
        for item in items
    ]
    return {
        "explanation_mode": mode,
        "evidence_status": packet.get("evidence_status") or "NO_EVIDENCE",
        "evidence_items": items,
        "sources": sources,
    }


def _safe_exam_evidence_summary(db: Session, unit: models.StudyUnit) -> dict[str, Any]:
    """Summarize only practice-trust-ready primary questions for one unit."""

    from app.services.practice import safe_canonical_questions

    if unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        questions = safe_canonical_questions(db, course_id=unit.course_id, study_unit_id=unit.id)
    else:
        questions = [
            db.get(models.Question, link.question_id)
            for link in unit.question_links
            if link.is_active is not False
        ]
        questions = [question for question in questions if question is not None and is_practice_trust_ready(question)]

    years = sorted({int(question.exam_year) for question in questions if question.exam_year is not None})
    material_names = []
    for question in questions:
        material = db.get(models.Material, question.source_material_id) if question.source_material_id else None
        name = str(material.name).strip() if material and material.name else ""
        if name and name not in material_names:
            material_names.append(name)
    if years:
        year_text = "、".join(str(year) for year in years)
        text = f"当前绑定 {len(questions)} 道可练真题：{year_text}"
    elif questions:
        text = f"已绑定 {len(questions)} 道可练真题"
    else:
        text = "当前没有可练真题"
    return {
        "safe_question_count": len(questions),
        "exam_years": years,
        "material_names": material_names[:3],
        "text": text,
    }


def _ranking(course: models.Course, db: Session) -> dict[str, dict[str, Any]]:
    from app.services import ranking_v1

    payload = ranking_v1.get_course_ranking(course, db=db, limit=367)
    return {row["canonical_kp_id"]: row for row in payload["items"]}


def _practice_binding(db: Session, unit: models.StudyUnit, ranking: dict[str, Any] | None) -> dict[str, Any]:
    if unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        from app.services.practice import safe_canonical_questions

        questions = safe_canonical_questions(db, course_id=unit.course_id, study_unit_id=unit.id)
    else:
        questions = [
            db.get(models.Question, link.question_id)
            for link in unit.question_links
            if link.is_active is not False and db.get(models.Question, link.question_id) is not None
        ]
        questions = [question for question in questions if is_practice_trust_ready(question)]
    ready = bool(questions)
    return {
        "practice_question_count": len(questions),
        "practice_question_binding_ready": ready,
        "practice_binding_status": (
            (ranking or {}).get("practice_binding_status")
            or ("READY_PRIMARY_QUESTION" if ready else "NO_PRIMARY_QUESTION")
        ),
    }


def _unit_representation(
    db: Session,
    user: models.User,
    course: models.Course,
    unit: models.StudyUnit,
    ranking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = _latest_learning_records(db, user.id, unit.id)
    from app.services.practice_metrics import practice_metrics

    metrics = practice_metrics(db, user_id=user.id, unit=unit)
    active_session = (
        db.query(models.LearningSession)
        .filter(
            models.LearningSession.user_id == user.id,
            models.LearningSession.course_id == course.id,
            models.LearningSession.study_unit_id == unit.id,
            models.LearningSession.completed_at.is_(None),
        )
        .order_by(models.LearningSession.started_at.desc(), models.LearningSession.id.desc())
        .first()
    )
    if not records and active_session is None and not metrics["attempted_question_count"]:
        exposure_status = "NOT_STARTED"
    elif active_session is not None:
        exposure_status = "IN_PROGRESS"
    else:
        exposure_status = "EXPOSED"
    is_graph = unit.canonical_graph_version == CANONICAL_GRAPH_VERSION
    verified_status = "UNKNOWN" if unit.mastery_status == "SKIPPED" else unit.mastery_status
    rank = ranking or {}
    hierarchy = _hierarchy(unit.canonical_kp_id, unit) if is_graph and unit.canonical_kp_id else {
        "canonical_id": unit.canonical_kp_id,
        "node_role": "KNOWLEDGE_POINT",
        "parent_canonical_id": None,
        "depth": 0,
        "order": 0,
        "structural_path": [unit.title],
        "name_cn": unit.title,
        "name_en": None,
        "aliases": [],
    }
    title = hierarchy.get("name_cn") or hierarchy.get("name_en") or unit.title
    return {
        "id": unit.id,
        "study_unit_id": unit.id,
        "canonical_kp_id": unit.canonical_kp_id,
        "canonical_graph_version": unit.canonical_graph_version,
        "title": title,
        "display_title": title,
        "hierarchy": hierarchy,
        "ranking_position": rank.get("ranking_position"),
        "exam_evidence_tier": rank.get("exam_evidence_tier"),
        "ranking_entity_role": rank.get("ranking_entity_role"),
        "display_priority_score": rank.get("display_priority_score"),
        "DISPLAY_SCORE_IS_RELATIVE_POLICY_SCORE_NOT_PROBABILITY": rank.get(
            "DISPLAY_SCORE_IS_RELATIVE_POLICY_SCORE_NOT_PROBABILITY", True
        ),
        "importance_label": unit.importance_label,
        "mastery_status": verified_status,
        "verified_mastery_status": verified_status,
        "coverage_status": metrics["coverage_status"],
        "exposure_status": exposure_status,
        "coverage_percent": metrics["coverage_percent"],
        "mastery_percent": metrics["mastery_percent"],
        "practice_attempted_count": metrics["attempted_question_count"],
        "valid_question_count": metrics["valid_question_count"],
        "active_session_id": active_session.id if active_session else None,
        "progress": metrics["mastery_percent"],
        "study_preference": _student_preference(records),
        "self_assessed_mastery": _self_assessed(records),
        "estimated_minutes": unit.estimated_minutes or 10,
        **_practice_binding(db, unit, rank if is_graph else None),
        "evidence_provenance": _evidence_provenance(unit.canonical_kp_id) if is_graph and unit.canonical_kp_id else [],
    }


def student_population(db: Session, user: models.User, course: models.Course) -> list[dict[str, Any]]:
    if is_graph_course(db, course.id):
        units = db.query(models.StudyUnit).filter(
            models.StudyUnit.course_id == course.id,
            models.StudyUnit.canonical_graph_version == CANONICAL_GRAPH_VERSION,
        ).all()
        ranks = _ranking(course, db)
        rows = [_unit_representation(db, user, course, unit, ranks.get(unit.canonical_kp_id)) for unit in units]
        return sorted(rows, key=lambda row: (row["ranking_position"] or 10_000, row["id"]))
    units = canonical_study_unit_query(db, course.id).all()
    return [_unit_representation(db, user, course, unit) for unit in units]


def unit_representation(db: Session, user: models.User, course: models.Course, unit: models.StudyUnit) -> dict[str, Any]:
    ranks = _ranking(course, db) if unit.canonical_graph_version == CANONICAL_GRAPH_VERSION else {}
    return _unit_representation(db, user, course, unit, ranks.get(unit.canonical_kp_id))


def course_progress(db: Session, user: models.User, course: models.Course) -> dict[str, Any]:
    rows = student_population(db, user, course)
    if not rows:
        return {"coverage": 0.0, "mastery": 0.0, "important_coverage": 0.0, "important_mastery": 0.0}
    important = [row for row in rows if row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE"] if is_graph_course(db, course.id) else [row for row in rows if row.get("importance_label") == "HIGH"]
    covered = [row for row in rows if row["coverage_status"] == "COVERED"]
    mastered = [row for row in rows if row["coverage_status"] == "COVERED" and row["mastery_percent"] >= 80]
    important = important or rows
    important_covered = [row for row in important if row["coverage_status"] == "COVERED"]
    important_mastered = [row for row in important if row["coverage_status"] == "COVERED" and row["mastery_percent"] >= 80]
    return {
        "coverage": round(len(covered) / len(rows) * 100, 1),
        "mastery": round(len(mastered) / len(rows) * 100, 1),
        "important_coverage": round(len(important_covered) / len(important) * 100, 1),
        "important_mastery": round(len(important_mastered) / len(important) * 100, 1),
        "student_population_mode": population_mode(db, course.id),
        "student_unit_count": len(rows),
        "important_unit_count": len(important),
    }


def exam_focus_summary(db: Session, user: models.User, course: models.Course) -> dict[str, int]:
    """Return the frozen truth-exam focus counts without creating another ranking."""

    rows = student_population(db, user, course)
    active = [row for row in rows if row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE"]
    return {
        "real_exam_active_count": len(active),
        "practice_ready_count": sum(1 for row in active if row.get("practice_question_binding_ready")),
        "supplementary_count": max(0, len(rows) - len(active)),
    }


def _recommendation_key(row: dict[str, Any], phase: str) -> tuple[Any, ...]:
    """Apply a bounded deterministic policy over the frozen ranking attributes."""

    active = row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE"
    ready = bool(row.get("practice_question_binding_ready"))
    status = row.get("mastery_status") or "UNKNOWN"
    coverage = row.get("coverage_status") or "NOT_COVERED"
    position = row.get("ranking_position") or 10_000
    status_order = {"REVIEW": 0, "WEAK": 1, "LEARNING": 2, "UNKNOWN": 3, "MASTERED": 4}
    status_rank = status_order.get(status, 3)

    if phase == "COVERAGE":
        # Coverage matters materially in the middle window, while unresolved
        # work remains a tie-breaker inside the same evidence tier.
        coverage_bucket = {"NOT_STARTED": 0, "NOT_COVERED": 0, "IN_PROGRESS": 1, "PARTIAL": 1, "COVERED": 2}.get(coverage, 1)
        return (
            coverage_bucket if active else 3,
            0 if ready else 1,
            status_rank,
            position,
        )

    if phase == "FINAL_SPRINT":
        if active and status in {"REVIEW", "WEAK"} and ready:
            bucket = 0
        elif active and ready:
            bucket = 1
        elif active:
            bucket = 2
        elif status in {"REVIEW", "WEAK"} and ready:
            bucket = 3
        else:
            bucket = 4
        return (bucket, status_rank, 0 if ready else 1, position)

    # Earlier study favors unresolved real-exam work, then the frozen order.
    return (0 if active else 1, status_rank, 0 if ready else 1, position)


def _recommendation_reason(row: dict[str, Any], phase: str, days_remaining: int | None) -> str:
    status = row.get("mastery_status") or "UNKNOWN"
    active = row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE"
    ready = bool(row.get("practice_question_binding_ready"))
    position = row.get("ranking_position")
    status_text = {
        "REVIEW": "最近做错过，需要复习",
        "WEAK": "练习表现偏弱，需要加强",
        "LEARNING": "正在学习验证",
        "UNKNOWN": "尚未完成验证",
        "MASTERED": "继续巩固",
    }.get(status, "需要关注")
    if phase == "FINAL_SPRINT" and days_remaining is not None:
        if active and status in {"REVIEW", "WEAK"}:
            prefix = f"距离考试还有 {days_remaining} 天，优先补你做错过的真题重点"
        elif active:
            prefix = f"距离考试还有 {days_remaining} 天，优先练习可作答的真题重点"
        else:
            prefix = f"距离考试还有 {days_remaining} 天，补充复习图谱知识"
    elif phase == "COVERAGE" and days_remaining is not None:
        prefix = f"距离考试还有 {days_remaining} 天，优先扩大真题重点覆盖"
    else:
        prefix = "先巩固真题重点，再补充完整知识图谱" if active else "作为真题重点之外的补充知识"
    rank_text = f"；真题重点中优先级第 {position}" if active and position else ""
    practice_text = "可直接练习真题" if ready else "当前暂无可练真题"
    evidence_text = (row.get("exam_evidence_summary") or {}).get("text") if active else None
    evidence_suffix = f"；{evidence_text}" if evidence_text else ""
    return f"{prefix}{rank_text}；{status_text}；{practice_text}{evidence_suffix}。"


def _action_copy(phase: str, count: int) -> tuple[str, str]:
    if phase == "FINAL_SPRINT":
        return f"今天先做这 {count} 项", "优先处理做错过 / 可练的真题重点；其余补充知识可以暂时后置。"
    if phase == "COVERAGE":
        return "接下来先补这几项", "先补还没覆盖的真题重点。"
    return "接下来先练这几项", "先把重要且薄弱的知识练稳。"


def _action_candidates(rows: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    available = [row for row in rows if row.get("study_preference") != "DEFERRED"]
    active = [row for row in available if row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE"]
    unresolved_active = [row for row in active if row.get("mastery_status") != "MASTERED"]
    if unresolved_active:
        return sorted(unresolved_active, key=lambda row: _recommendation_key(row, phase))
    unresolved = [row for row in available if row.get("mastery_status") != "MASTERED"]
    if unresolved:
        return sorted(unresolved, key=lambda row: _recommendation_key(row, phase))
    return sorted(available, key=lambda row: _recommendation_key(row, phase))


def recommendation(db: Session, user: models.User, course: models.Course, phase: str, days_remaining: int | None) -> dict[str, Any]:
    rows = student_population(db, user, course)
    if not rows:
        return {}
    if is_graph_course(db, course.id):
        candidates = _action_candidates(rows, phase) or rows
        chosen = min(candidates, key=lambda row: _recommendation_key(row, phase))
        unit = db.get(models.StudyUnit, chosen["id"])
        if unit is not None:
            chosen = {**chosen, "exam_evidence_summary": _safe_exam_evidence_summary(db, unit)}
        return {
            "study_unit": chosen,
            "reason": {"type": phase, "text": _recommendation_reason(chosen, phase, days_remaining)},
            "estimated_minutes": chosen["estimated_minutes"],
            "phase": phase,
            "days_remaining": days_remaining,
        }
    return {}


def action_batch(db: Session, user: models.User, course: models.Course, phase: str, days_remaining: int | None) -> dict[str, Any]:
    """Return a small next-action list using the same deterministic selector."""

    if not is_graph_course(db, course.id):
        return {"phase": phase, "days_remaining": days_remaining, "items": []}
    rows = student_population(db, user, course)
    cap = {"STRENGTHENING": 5, "COVERAGE": 4, "FINAL_SPRINT": 3}.get(phase, 5)
    selected = _action_candidates(rows, phase)[:cap]
    items = []
    for row in selected:
        unit = db.get(models.StudyUnit, row["id"])
        item = dict(row)
        if unit is not None:
            item["exam_evidence_summary"] = _safe_exam_evidence_summary(db, unit)
        item["action_reason"] = _recommendation_reason(item, phase, days_remaining)
        items.append(item)
    title, reason = _action_copy(phase, len(items))
    return {
        "phase": phase,
        "days_remaining": days_remaining,
        "title": title,
        "reason": reason,
        "items": items,
    }


def review_items(db: Session, user: models.User, course: models.Course) -> list[dict[str, Any]]:
    rows = student_population(db, user, course)
    items = []
    for row in rows:
        if row["mastery_status"] not in {"WEAK", "REVIEW", "LEARNING"}:
            continue
        accuracy = row.get("mastery_percent") if row.get("practice_attempted_count") else None
        items.append({
            "study_unit_id": row["id"], "title": row["title"], "importance_label": row.get("importance_label"),
            "importance_text": "真题重点" if row.get("exam_evidence_tier") == "REAL_EXAM_ACTIVE" else "知识图谱",
            "mastery_status": row["mastery_status"], "recent_accuracy": accuracy,
            "coverage_status": row["coverage_status"], "coverage_percent": row["coverage_percent"],
            "estimated_minutes": row["estimated_minutes"], "canonical_kp_id": row.get("canonical_kp_id"),
            "ranking_position": row.get("ranking_position"),
        })
    return sorted(items, key=lambda item: item.get("ranking_position") or 10_000)


def knowledge_view(db: Session, user: models.User, course: models.Course) -> dict[str, Any] | None:
    if not is_graph_course(db, course.id):
        return None
    rows = student_population(db, user, course)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = row["hierarchy"]["structural_path"]
        domain_key = "/".join(path[:2]) if len(path) > 1 else (path[0] if path else "未分类")
        section_key = "/".join(path[:-1]) if len(path) > 2 else domain_key
        domain = grouped.setdefault(domain_key, {"id": domain_key, "title": path[1] if len(path) > 1 else domain_key, "sections": {}})
        section = domain["sections"].setdefault(section_key, {"id": section_key, "title": path[-2] if len(path) > 1 else domain_key, "children": []})
        section["children"].append(row)
    domains = []
    for domain in grouped.values():
        sections = list(domain["sections"].values())
        for section in sections:
            section["children"].sort(key=lambda item: (item.get("ranking_position") or 10_000, item["title"]))
        domains.append({"id": domain["id"], "title": domain["title"], "sections": sections})
    domains.sort(key=lambda item: item["id"])
    return {"mode": "CANONICAL_GRAPH", "total": len(rows), "domains": domains}


def wrong_book(db: Session, user: models.User, course: models.Course, unresolved_only: bool = True) -> list[dict[str, Any]]:
    records = (
        db.query(models.PracticeRecord)
        .join(models.Question, models.Question.id == models.PracticeRecord.question_id)
        .filter(models.PracticeRecord.user_id == user.id, models.Question.course_id == course.id)
        .order_by(models.PracticeRecord.created_at.asc(), models.PracticeRecord.id.asc())
        .all()
    )
    grouped: dict[tuple[str, str], list[models.PracticeRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.question_id, record.study_unit_id or "")].append(record)
    result = []
    for (_question_id, _unit_id), history in grouped.items():
        latest = history[-1]
        if unresolved_only and latest.correct:
            continue
        question = db.get(models.Question, latest.question_id)
        unit = db.get(models.StudyUnit, latest.study_unit_id) if latest.study_unit_id else None
        if question is None or unit is None or not is_practice_trust_ready(question):
            continue
        previous = history[-2] if len(history) > 1 else None
        material = db.get(models.Material, question.source_material_id) if question.source_material_id else None
        result.append({
            "question_id": question.id, "study_unit_id": unit.id, "title": unit.title,
            "knowledge_point_title": unit.title, "content": question.content,
            "previous_answer": previous.answer if previous else None, "latest_answer": latest.answer,
            "correct_answer": question.answer, "explanation": trusted_explanation(question.explanation, question.answer),
            "source_material": material.name if material else None, "exam_year": question.exam_year,
            "question_number": question.question_number,
            "source_location": question.source_location, "resolved": bool(latest.correct),
            "latest_attempt_at": latest.created_at.isoformat() if latest.created_at else None,
        })
    return sorted(result, key=lambda item: item["latest_attempt_at"] or "", reverse=True)


def explanation_provenance(unit: models.StudyUnit) -> list[dict[str, Any]]:
    return _evidence_provenance(unit.canonical_kp_id) if unit.canonical_graph_version == CANONICAL_GRAPH_VERSION and unit.canonical_kp_id else []
