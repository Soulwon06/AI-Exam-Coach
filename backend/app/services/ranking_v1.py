"""Read-only production adapter for the frozen Database KP ranking v1."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from app import models
from app.services import practice


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "evaluation" / "config" / "database_kp_ranking_policy_v1.json"
GOLDEN_PATH = ROOT / "evaluation" / "datasets" / "database_kp_ranking_v1_golden_shadow.json"
POLICY_SHA256 = "f8a9b4502e89b1ed98a627650f25821a08c2c38732201a7d4c3165b32bd5172d"
GOLDEN_SHA256 = "4944c4fdeb93daebd1fbb4ad5f326694f708f9d44e78a2220baf1c1c08f9ab28"

POLICY_VERSION = "DATABASE_KP_RANKING_POLICY_V1"
RANKING_VIEW = "VIEW_C_ACTIONABLE_MIXED"
PILOT_COURSE_ID = "2fac5adf-a99b-47f1-838d-08563331a5f1"
COURSE_SCOPE = "DATABASE_SYSTEMS_PILOT"
ACTIVE_TIER = "REAL_EXAM_ACTIVE"
ZERO_TIER = "NO_REAL_EXAM_EVIDENCE_CURRENT_CORPUS"
ALLOWED_ENTITY_ROLES = {"ACTIONABLE_LEAF", "EXAM_UMBRELLA_NON_LEAF"}
CANONICAL_GRAPH_VERSION = "DATABASE_CANONICAL_GRAPH_V1"


class RankingV1ContractError(RuntimeError):
    """Raised when frozen ranking artifacts do not satisfy the read contract."""


class RankingV1NotAvailableError(RuntimeError):
    """Raised when a course is not the exact approved pilot identity."""


_CACHE: tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]] | None = None


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankingV1ContractError(f"RANKING_V1_ARTIFACT_INVALID:{path.name}") from exc


def _assert_pinned_sha(path: Path, expected: str) -> None:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RankingV1ContractError(f"RANKING_V1_ARTIFACT_UNREADABLE:{path.name}") from exc
    if actual != expected:
        raise RankingV1ContractError(f"RANKING_V1_ARTIFACT_SHA_MISMATCH:{path.name}")


def _validate(policy: dict[str, Any], golden: dict[str, Any]) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    if policy.get("version") != POLICY_VERSION:
        raise RankingV1ContractError("POLICY_VERSION_MISMATCH")
    if policy.get("status") != "FROZEN_POLICY_CONTRACT_NOT_PRODUCTION_INTEGRATION":
        raise RankingV1ContractError("POLICY_STATUS_MISMATCH")
    if policy.get("ranking_membership", {}).get("view") != RANKING_VIEW:
        raise RankingV1ContractError("POLICY_VIEW_MISMATCH")
    if policy.get("ranking_membership", {}).get("count") != 367:
        raise RankingV1ContractError("POLICY_MEMBER_COUNT_MISMATCH")
    coefficients = policy.get("formula", {}).get("coefficients", {})
    expected_coefficients = {
        "exam_year_breadth": 0.55,
        "occurrence_log_signal": 0.25,
        "primary_log_signal": 0.10,
        "cross_paper_same_year_bonus": 0.05,
        "textbook_support_signal": 0.05,
    }
    if coefficients != expected_coefficients or policy.get("formula", {}).get("weights_sum") != 1.0:
        raise RankingV1ContractError("POLICY_FORMULA_MISMATCH")
    display_semantics = policy.get("display_score_semantics", {})
    if display_semantics.get("decimals") != 2 or display_semantics.get("DISPLAY_SCORE_IS_RELATIVE_POLICY_SCORE_NOT_PROBABILITY") is not True:
        raise RankingV1ContractError("POLICY_DISPLAY_CONTRACT_MISMATCH")
    if policy.get("DISPLAY_SCORE_USED_FOR_SORTING") is not False:
        raise RankingV1ContractError("DISPLAY_SCORE_SORT_CONTRACT_MISMATCH")
    textbook = policy.get("textbook_semantics", {})
    if textbook.get("explanation_bound") != 1.0 or textbook.get("structure_only") != 0.25 or textbook.get("max_contribution") != 0.05:
        raise RankingV1ContractError("POLICY_TEXTBOOK_CONTRACT_MISMATCH")
    if textbook.get("policy_status") != "FROZEN_POLICY_V1_ASSUMPTION" or textbook.get("origin") != "D5_A_SIMULATION_SELECTED_AND_FROZEN":
        raise RankingV1ContractError("POLICY_TEXTBOOK_STATUS_MISMATCH")
    if "SIMULATION_ONLY" in json.dumps(policy, ensure_ascii=False):
        raise RankingV1ContractError("STALE_SIMULATION_ONLY_STATUS")
    if policy.get("real_exam_active_gate", {}).get("reason") != "PRESERVE_TRUE_EXAM_FIRST_UNDER_FUTURE_SOURCE_OR_WEIGHT_CHANGES":
        raise RankingV1ContractError("POLICY_GATE_REASON_MISMATCH")
    if policy.get("real_exam_active_gate", {}).get("is_additional_score") is not False:
        raise RankingV1ContractError("POLICY_GATE_SCORE_MISMATCH")
    if policy.get("excluded_signals") != ["CLASS_NOTES", "TEACHER_PPT", "TEACHER_EMPHASIS", "EXAM_SCOPE", "HOMEWORK", "LAB", "SUPPLEMENTARY_REVIEW_QA"]:
        raise RankingV1ContractError("POLICY_EXCLUDED_SIGNAL_MISMATCH")

    if golden.get("policy_version") != POLICY_VERSION or golden.get("status") != "GOLDEN_SHADOW_NOT_PRODUCTION" or golden.get("ranking_view") != RANKING_VIEW:
        raise RankingV1ContractError("GOLDEN_POLICY_VERSION_MISMATCH")
    rows = golden.get("rows")
    if golden.get("row_count") != 367 or not isinstance(rows, list) or len(rows) != 367:
        raise RankingV1ContractError("GOLDEN_ROW_COUNT_MISMATCH")
    ids = [row.get("canonical_kp_id") for row in rows]
    positions = [row.get("ranking_position") for row in rows]
    if len(set(ids)) != 367 or positions != list(range(1, 368)):
        raise RankingV1ContractError("GOLDEN_ID_OR_POSITION_CONTRACT_FAILED")
    if any(row.get("ranking_position") != index for index, row in enumerate(rows, start=1)):
        raise RankingV1ContractError("GOLDEN_ORDER_CONTRACT_FAILED")
    active = rows[:64]
    zero = rows[64:]
    if any(row.get("exam_evidence_tier") != ACTIVE_TIER for row in active) or any(row.get("exam_evidence_tier") != ZERO_TIER for row in zero):
        raise RankingV1ContractError("GOLDEN_EXAM_TIER_BOUNDARY_FAILED")
    if sum(row.get("ranking_entity_role") == "EXAM_UMBRELLA_NON_LEAF" for row in rows) != 6:
        raise RankingV1ContractError("GOLDEN_UMBRELLA_COUNT_FAILED")
    for row in rows:
        if row.get("ranking_entity_role") not in ALLOWED_ENTITY_ROLES:
            raise RankingV1ContractError("GOLDEN_ENTITY_ROLE_INVALID")
        if row.get("evidence_aggregation_mode") != "DIRECT_ONLY":
            raise RankingV1ContractError("GOLDEN_EVIDENCE_AGGREGATION_INVALID")
        if row.get("DISPLAY_SCORE_IS_RELATIVE_POLICY_SCORE_NOT_PROBABILITY") is not True:
            raise RankingV1ContractError("GOLDEN_SCORE_SEMANTICS_INVALID")
        if row.get("display_priority_score") != round(row.get("ranking_score") * 100, 2):
            raise RankingV1ContractError("GOLDEN_DISPLAY_SCORE_INVALID")
        if row.get("no_priority_label_assigned") is not True:
            raise RankingV1ContractError("GOLDEN_PRIORITY_LABEL_CONTRACT_FAILED")
    return _freeze(policy), tuple(_freeze(row) for row in rows)


def _load_cache() -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    global _CACHE
    if _CACHE is None:
        _assert_pinned_sha(POLICY_PATH, POLICY_SHA256)
        _assert_pinned_sha(GOLDEN_PATH, GOLDEN_SHA256)
        policy = _load_json(POLICY_PATH)
        golden = _load_json(GOLDEN_PATH)
        _CACHE = _validate(policy, golden)
    return _CACHE


def reset_cache_for_tests() -> None:
    """Reset the process cache for isolated contract tests only."""
    global _CACHE
    _CACHE = None


def validate_frozen_artifacts() -> dict[str, Any]:
    policy, rows = _load_cache()
    return {
        "policy_version": policy["version"],
        "ranking_view": RANKING_VIEW,
        "row_count": len(rows),
        "validated": True,
    }


def verify_frozen_identity_score_contract() -> dict[str, Any]:
    """Verify ranking identity/order/score from the pinned golden artifact.

    This is deliberately a read-only contract check. It does not recompute
    ranking, consult production rows, or infer stability from an audit flag.
    """
    _policy, rows = _load_cache()
    identity_order = [
        {"canonical_kp_id": row["canonical_kp_id"], "ranking_position": row["ranking_position"]}
        for row in rows
    ]
    identity_order_scores = [
        {
            "canonical_kp_id": row["canonical_kp_id"],
            "ranking_position": row["ranking_position"],
            "ranking_score": row["ranking_score"],
        }
        for row in rows
    ]
    identity_order_sha = hashlib.sha256(
        json.dumps(identity_order, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    identity_order_score_sha = hashlib.sha256(
        json.dumps(identity_order_scores, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    positions_valid = [row["ranking_position"] for row in rows] == list(range(1, len(rows) + 1))
    scores_valid = all(
        isinstance(row["ranking_score"], (int, float))
        and row["display_priority_score"] == round(row["ranking_score"] * 100, 2)
        for row in rows
    )
    return {
        "artifact_sha256": GOLDEN_SHA256,
        "row_count": len(rows),
        "identity_order_sha256": identity_order_sha,
        "identity_order_score_sha256": identity_order_score_sha,
        "identity_order_verified": positions_valid and len(identity_order) == 367,
        "identity_score_verified": scores_valid and len(identity_order_scores) == 367,
    }


def assert_course_scope(course: Any) -> None:
    if getattr(course, "id", None) != PILOT_COURSE_ID:
        raise RankingV1NotAvailableError("RANKING_V1_NOT_AVAILABLE_FOR_COURSE")


def _load_exact_bindings(db: Any, course: Any, rows: tuple[Mapping[str, Any], ...]) -> dict[str, models.StudyUnit] | None:
    if db is None or not hasattr(db, "query"):
        return None
    query_rows = (
        db.query(models.StudyUnit)
        .filter(
            models.StudyUnit.course_id == course.id,
            models.StudyUnit.canonical_graph_version == CANONICAL_GRAPH_VERSION,
        )
        .all()
    )
    expected_ids = [row["canonical_kp_id"] for row in rows]
    by_kp: dict[str, models.StudyUnit] = {}
    for unit in query_rows:
        if not unit.canonical_kp_id or unit.canonical_kp_id in by_kp:
            raise RankingV1ContractError("RANKING_V1_DUPLICATE_STUDY_UNIT_BINDING")
        by_kp[unit.canonical_kp_id] = unit
    if set(by_kp) != set(expected_ids) or len(by_kp) != len(expected_ids):
        raise RankingV1ContractError("RANKING_V1_INCOMPLETE_STUDY_UNIT_BINDING")
    if any(unit.course_id != course.id or unit.canonical_graph_version != CANONICAL_GRAPH_VERSION for unit in by_kp.values()):
        raise RankingV1ContractError("RANKING_V1_INVALID_STUDY_UNIT_BINDING")
    return by_kp


def _safe_practice_binding(db: Any, unit: models.StudyUnit, *, exam_active: bool) -> dict[str, Any]:
    """Compute practice readiness from safe primary Question eligibility.

    Ranking evidence membership is intentionally independent from this bridge.
    A secondary mapping may contribute to ranking evidence but cannot make a
    canonical StudyUnit practice-ready.
    """
    safe_questions = practice.safe_canonical_questions(
        db,
        course_id=unit.course_id,
        study_unit_id=unit.id,
    )
    practice_question_count = len(safe_questions)
    primary_exam_query = (
        db.query(models.Question)
        .join(models.QuestionStudyUnit, models.QuestionStudyUnit.question_id == models.Question.id)
        .filter(
            models.QuestionStudyUnit.study_unit_id == unit.id,
            models.QuestionStudyUnit.is_primary == True,  # noqa: E712
            models.QuestionStudyUnit.is_active.isnot(False),
        )
    )
    if not exam_active:
        status = "NO_REAL_EXAM_QUESTION"
    elif practice_question_count:
        status = "READY_PRIMARY_QUESTION"
    elif unit.canonical_graph_version != CANONICAL_GRAPH_VERSION:
        status = "NO_REAL_EXAM_QUESTION"
    elif primary_exam_query.filter(models.Question.image_required == True).count():  # noqa: E712
        status = "IMAGE_DEPENDENCY_NOT_SERVABLE"
    elif unit.canonical_graph_version == CANONICAL_GRAPH_VERSION:
        status = "NO_PRIMARY_QUESTION"
    else:
        status = "NO_REAL_EXAM_QUESTION"
    return {
        "practice_question_count": practice_question_count,
        "practice_binding_status": status,
        "practice_question_binding_ready": practice_question_count > 0,
    }


def get_ranked_kps(course: Any, *, db: Any = None, limit: int = 50, offset: int = 0, exam_evidence_tier: str | None = None, entity_role: str | None = None) -> dict[str, Any]:
    assert_course_scope(course)
    if limit < 1 or limit > 367:
        raise ValueError("limit must be between 1 and 367")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if exam_evidence_tier not in (None, ACTIVE_TIER, ZERO_TIER):
        raise ValueError("invalid exam_evidence_tier")
    if entity_role not in (None, *sorted(ALLOWED_ENTITY_ROLES)):
        raise ValueError("invalid entity_role")
    policy, rows = _load_cache()
    bindings = _load_exact_bindings(db, course, rows)
    filtered = [row for row in rows if (exam_evidence_tier is None or row["exam_evidence_tier"] == exam_evidence_tier) and (entity_role is None or row["ranking_entity_role"] == entity_role)]
    items = [_thaw(row) for row in filtered[offset : offset + limit]]
    for item in items:
        item["display_score_is_probability"] = False
        if bindings is not None:
            unit = bindings[item["canonical_kp_id"]]
            practice_binding = _safe_practice_binding(
                db,
                unit,
                exam_active=item["exam_evidence_tier"] == ACTIVE_TIER,
            )
            item.update(
                {
                    "study_unit_id": unit.id,
                    "study_unit_binding_status": "BOUND_EXACT_CANONICAL_ID",
                    "mastery_status": unit.mastery_status,
                    "coverage_status": unit.coverage_status,
                    "progress": unit.progress,
                    "estimated_minutes": unit.estimated_minutes,
                    **practice_binding,
                }
            )
    return {
        "policy_version": policy["version"],
        "ranking_view": RANKING_VIEW,
        "score_semantics": "RELATIVE_POLICY_SCORE_NOT_PROBABILITY",
        "total": len(rows),
        "filtered_total": len(filtered),
        "offset": offset,
        "limit": limit,
        "items": items,
        **(
            {
                "study_unit_materialization": {
                    "version": CANONICAL_GRAPH_VERSION,
                    "exact_bound": len(bindings),
                }
            }
            if bindings is not None
            else {}
        ),
    }


def get_course_ranking(course: Any, **kwargs: Any) -> dict[str, Any]:
    return get_ranked_kps(course, **kwargs)


def get_ranked_kp(course: Any, canonical_kp_id: str) -> dict[str, Any] | None:
    result = get_ranked_kps(course, limit=367)
    return next((item for item in result["items"] if item["canonical_kp_id"] == canonical_kp_id), None)
