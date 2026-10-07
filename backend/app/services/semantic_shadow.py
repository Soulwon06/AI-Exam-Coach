"""Bounded Course Brain v2 semantic shadow contracts and cache.

This module is deliberately separate from the production Course Brain.  It
accepts one already-persisted text chunk, validates a provider response, and
stores only a versioned local shadow result.  It never parses source files or
mutates StudyUnit/Question rows.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


SEMANTIC_PIPELINE_VERSION = "course-brain-v2-shadow-v1"
PROMPT_VERSION = "course-brain-v2-knowledge-points-v2"
SCHEMA_VERSION = "knowledge-point-candidate-v2"
MAX_CANDIDATES_PER_SECTION = 8
MAX_ALIASES_PER_CANDIDATE = 4
MAX_EVIDENCE_REFS_PER_CANDIDATE = 2
MAX_EVIDENCE_EXCERPT_CHARS = 300
MAX_LEARNING_OBJECTIVE_CHARS = 80


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    excerpt: str = Field(min_length=1)
    provider_suggested_start: int | None = Field(default=None, ge=0)
    provider_suggested_end: int | None = Field(default=None, gt=0)
    resolved_source_start: int | None = Field(default=None, ge=0)
    resolved_source_end: int | None = Field(default=None, gt=0)
    canonical_excerpt: str | None = None
    resolution_status: Literal["EXACT", "NORMALIZED_EXACT", "UNRESOLVED", "AMBIGUOUS"] | None = None
    resolution_method: Literal["EXACT", "NORMALIZED_EXACT", "UNRESOLVED", "AMBIGUOUS"] | None = None


class KnowledgePointCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    canonical_name_zh: str = Field(min_length=1)
    canonical_name_en: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    parent_hint_zh: str | None = None
    parent_hint_en: str | None = None
    learning_objective_zh: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    decision: Literal["ACCEPT", "REVIEW", "ABSTAIN"]
    review_signals: list[str] = Field(default_factory=list)
    validation_result: Literal["PASS", "REVIEW", "FAIL"] | None = None


class SemanticProviderError(RuntimeError):
    """Provider failure that is safe to expose in the local report."""


class SemanticProviderTimeout(SemanticProviderError):
    """A provider timeout with a non-secret, classifiable reason."""


class SemanticProviderHTTPError(SemanticProviderError):
    """A non-2xx provider response with sanitized error metadata."""

    def __init__(
        self,
        status_code: int,
        *,
        provider_error_code: str | None = None,
        provider_error_type: str | None = None,
        sanitized_provider_message: str | None = None,
    ) -> None:
        self.http_status_code = status_code
        self.provider_error_code = provider_error_code
        self.provider_error_type = provider_error_type
        self.sanitized_provider_message = sanitized_provider_message
        self.provider_response_received = True
        super().__init__(f"HTTP_{status_code}")


class SemanticProviderNetworkError(SemanticProviderError):
    """A transport failure before a usable provider response was received."""


class SemanticProviderResponseError(SemanticProviderError):
    """A provider response that cannot be consumed as an HTTP response."""


class SemanticProviderSchemaError(SemanticProviderError):
    """A successful response whose semantic JSON violates the contract."""


class SemanticProviderTruncatedResponse(SemanticProviderSchemaError):
    """A schema failure explicitly associated with provider length truncation."""


def sanitize_provider_text(value: Any, *, api_key: str | None = None, limit: int = 500) -> str:
    """Return bounded provider text without credentials or authorization data."""

    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r'(?i)(authorization\s*[:=]\s*["\']?)[^,}\r\n"\']+', r"\1[REDACTED]", text)
    return text[:limit]


def normalize_provider_response(content: str) -> str:
    """Apply only BOM/whitespace and one complete outer Markdown fence removal."""

    text = str(content or "").lstrip("\ufeff").strip()
    lines = text.splitlines()
    if len(lines) >= 3 and re.fullmatch(r"```(?:json)?", lines[0].strip(), flags=re.IGNORECASE) and lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1]).strip()
    return text


def parse_provider_json(content: str) -> Any:
    """Parse provider JSON without exposing response or credential contents."""
    try:
        return json.loads(normalize_provider_response(content))
    except json.JSONDecodeError:
        raise SemanticProviderSchemaError("SCHEMA_ERROR: provider returned invalid JSON") from None


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _identity_tokens(candidate: KnowledgePointCandidate) -> set[str]:
    values = [candidate.canonical_name_zh, candidate.canonical_name_en, *candidate.aliases]
    return {_normalise(value) for value in values if _normalise(value)}


def _compact_identity(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value or "").casefold()


def _normalised_with_spans(text: str, *, hyphen_space: bool = False) -> tuple[str, list[tuple[int, int]]]:
    """Normalize layout-only differences while retaining source coordinates."""

    output: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            end = index + 1
            while end < len(text) and text[end].isspace():
                end += 1
            if output and end < len(text):
                output.append(" ")
                spans.append((index, end))
            index = end
            continue
        if char == "-" and index + 1 < len(text) and text[index + 1].isspace():
            end = index + 2
            while end < len(text) and text[end].isspace():
                end += 1
            if end < len(text):
                if hyphen_space and output:
                    output.append(" ")
                    spans.append((index, end))
                index = end
                continue
        expanded = unicodedata.normalize("NFKC", char).casefold()
        for unit in expanded:
            output.append(unit)
            spans.append((index, index + 1))
        index += 1
    return "".join(output), spans


def _find_all(text: str, needle: str) -> list[int]:
    if not needle:
        return []
    positions: list[int] = []
    start = 0
    while True:
        found = text.find(needle, start)
        if found < 0:
            return positions
        positions.append(found)
        start = found + 1


class EvidenceResolver:
    """Resolve provider quotes to unique coordinates in one selected section."""

    def __init__(self, source_text: str, section_start: int, section_end: int) -> None:
        self.source_text = source_text
        self.section_start = section_start
        self.section_end = section_end
        section = source_text[section_start:section_end]
        self._section = section
        self._normalised_section, self._normalised_spans = _normalised_with_spans(section)

    def _result(self, method: str, start: int | None = None, end: int | None = None) -> dict[str, Any]:
        if start is None or end is None:
            return {
                "resolution_status": method,
                "resolution_method": method,
                "resolved_source_start": None,
                "resolved_source_end": None,
                "canonical_excerpt": None,
                "resolved_full_span": None,
            }
        absolute_start = self.section_start + start
        absolute_end = self.section_start + end
        display_end = min(absolute_end, absolute_start + MAX_EVIDENCE_EXCERPT_CHARS)
        return {
            "resolution_status": method,
            "resolution_method": method,
            "resolved_source_start": absolute_start,
            "resolved_source_end": absolute_end,
            "canonical_excerpt": self.source_text[absolute_start:display_end],
            "resolved_full_span": self.source_text[absolute_start:absolute_end],
        }

    def resolve(self, quote: str) -> dict[str, Any]:
        exact_positions = _find_all(self._section, quote)
        if len(exact_positions) == 1:
            start = exact_positions[0]
            return self._result("EXACT", start, start + len(quote))
        if len(exact_positions) > 1:
            return self._result("AMBIGUOUS")

        normalised_quote, _ = _normalised_with_spans(quote)
        normalised_quote = normalised_quote.strip()
        positions = _find_all(self._normalised_section, normalised_quote)
        if len(positions) == 0:
            spaced_section, spaced_spans = _normalised_with_spans(self._section, hyphen_space=True)
            spaced_positions = _find_all(spaced_section, normalised_quote)
            if len(spaced_positions) == 1:
                start_index = spaced_positions[0]
                end_index = start_index + len(normalised_quote) - 1
                if end_index < len(spaced_spans):
                    start = spaced_spans[start_index][0]
                    end = spaced_spans[end_index][1]
                    return self._result("NORMALIZED_EXACT", start, end)
            if len(spaced_positions) > 1:
                return self._result("AMBIGUOUS")
        if len(positions) != 1:
            return self._result("AMBIGUOUS" if len(positions) > 1 else "UNRESOLVED")
        start_index = positions[0]
        end_index = start_index + len(normalised_quote) - 1
        if end_index >= len(self._normalised_spans):
            return self._result("UNRESOLVED")
        start = self._normalised_spans[start_index][0]
        end = self._normalised_spans[end_index][1]
        return self._result("NORMALIZED_EXACT", start, end)


def validate_candidates(
    raw_candidates: Any,
    *,
    material_id: str,
    source_text: str,
    section_start: int | None = None,
    section_end: int | None = None,
) -> dict[str, Any]:
    """Validate and conservatively classify one provider response."""

    if isinstance(raw_candidates, dict):
        raw_candidates = raw_candidates.get("candidates", raw_candidates.get("knowledge_points"))
    if not isinstance(raw_candidates, list):
        return {"candidates": [], "errors": ["response must contain a candidates array"], "duplicates_detected": False}

    candidates: list[KnowledgePointCandidate] = []
    errors: list[str] = []
    duplicate_indexes: set[int] = set()
    identities: dict[str, int] = {}
    resolved_section_start = section_start if section_start is not None else 0
    resolved_section_end = section_end if section_end is not None else len(source_text)
    resolver = EvidenceResolver(source_text, resolved_section_start, resolved_section_end)

    if len(raw_candidates) > MAX_CANDIDATES_PER_SECTION:
        errors.append(f"candidate count exceeds {MAX_CANDIDATES_PER_SECTION}")

    for index, raw in enumerate(raw_candidates):
        try:
            candidate = KnowledgePointCandidate.model_validate(raw)
        except ValidationError as exc:
            errors.append(f"candidate[{index}] schema: {exc.errors(include_url=False)}")
            continue

        candidate_errors: list[str] = []
        review_signals = list(candidate.review_signals)
        if not candidate.canonical_name_zh.strip() or not candidate.canonical_name_en.strip():
            candidate_errors.append("canonical name is empty")
        if len(candidate.aliases) > MAX_ALIASES_PER_CANDIDATE:
            candidate_errors.append(f"aliases exceed {MAX_ALIASES_PER_CANDIDATE}")
        if len(candidate.learning_objective_zh) > MAX_LEARNING_OBJECTIVE_CHARS:
            candidate_errors.append(f"learning objective exceeds {MAX_LEARNING_OBJECTIVE_CHARS} chars")
        if len(candidate.evidence_refs) > MAX_EVIDENCE_REFS_PER_CANDIDATE:
            candidate_errors.append(f"evidence_refs exceed {MAX_EVIDENCE_REFS_PER_CANDIDATE}")
        if any(_compact_identity(alias) == "subsetdependency" for alias in candidate.aliases):
            review_signals.append("SUSPICIOUS_ALIAS")
        if candidate.decision == "ACCEPT" and not candidate.evidence_refs:
            candidate_errors.append("ACCEPT candidate has no evidence_ref")

        resolved_refs: list[EvidenceRef] = []
        resolved_ranges: list[tuple[int, int]] = []
        for evidence_index, evidence in enumerate(candidate.evidence_refs):
            evidence = evidence.model_copy(
                update={
                    "provider_suggested_start": evidence.source_start,
                    "provider_suggested_end": evidence.source_end,
                }
            )
            if evidence.material_id != material_id:
                candidate_errors.append(f"evidence[{evidence_index}] material_id mismatch")
                resolved_refs.append(evidence.model_copy(update={"resolution_status": "UNRESOLVED", "resolution_method": "UNRESOLVED"}))
                continue
            resolution = resolver.resolve(evidence.excerpt)
            evidence = evidence.model_copy(update=resolution)
            resolved_refs.append(evidence)
            if resolution["resolution_status"] in {"UNRESOLVED", "AMBIGUOUS"}:
                candidate_errors.append(
                    f"evidence[{evidence_index}] {resolution['resolution_status'].lower()} quote"
                )
            else:
                resolved_start = resolution["resolved_source_start"]
                resolved_end = resolution["resolved_source_end"]
                if resolved_start is not None and resolved_end is not None:
                    if any(start < resolved_end and resolved_start < end for start, end in resolved_ranges):
                        candidate_errors.append(f"evidence[{evidence_index}] overlaps another resolved evidence ref")
                    if (resolved_start, resolved_end) in resolved_ranges:
                        candidate_errors.append(f"evidence[{evidence_index}] duplicates another resolved evidence ref")
                    resolved_ranges.append((resolved_start, resolved_end))

        resolved_count = sum(
            evidence.resolution_status in {"EXACT", "NORMALIZED_EXACT"} for evidence in resolved_refs
        )
        hard_failure = any("material_id mismatch" in error for error in candidate_errors)
        if resolved_count and not hard_failure and not any(
            "exceeds" in error or "empty" in error for error in candidate_errors
        ):
            validation_result = "PASS"
            if candidate.decision != "ABSTAIN":
                candidate = candidate.model_copy(update={"decision": "ACCEPT"})
        elif resolved_count:
            validation_result = "REVIEW"
            if candidate.decision == "ACCEPT":
                candidate = candidate.model_copy(update={"decision": "REVIEW"})
        elif candidate.evidence_refs and not hard_failure:
            validation_result = "REVIEW"
            if candidate.decision == "ACCEPT":
                candidate = candidate.model_copy(update={"decision": "REVIEW"})
        else:
            validation_result = "FAIL"
            if candidate.decision != "ABSTAIN":
                candidate = candidate.model_copy(update={"decision": "ABSTAIN"})

        if candidate_errors:
            errors.extend(f"candidate[{index}]: {item}" for item in candidate_errors)
        candidate = candidate.model_copy(
            update={
                "evidence_refs": resolved_refs,
                "review_signals": sorted(set(review_signals)),
                "validation_result": validation_result,
            }
        )

        candidate_tokens = _identity_tokens(candidate)
        compact_tokens = {_compact_identity(value) for value in [candidate.canonical_name_en, *candidate.aliases] if _compact_identity(value)}
        all_identity_tokens = candidate_tokens | compact_tokens
        if any(token in identities for token in all_identity_tokens):
            duplicate_indexes.add(len(candidates))
        else:
            for token in all_identity_tokens:
                identities[token] = len(candidates)
        candidates.append(candidate)

    if duplicate_indexes:
        for index in duplicate_indexes:
            candidate = candidates[index]
            if candidate.decision == "ACCEPT":
                candidates[index] = candidate.model_copy(update={"decision": "REVIEW", "validation_result": "REVIEW"})
            errors.append(f"candidate[{index}]: duplicate canonical name or alias")

    return {
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "errors": errors,
        "duplicates_detected": bool(duplicate_indexes),
    }


def semantic_cache_key(
    *,
    source_hash: str,
    chunk_hash: str,
    provider: str,
    model: str,
    language: str = "zh-CN",
) -> str:
    material = "|".join(
        [
            source_hash,
            chunk_hash,
            SEMANTIC_PIPELINE_VERSION,
            PROMPT_VERSION,
            SCHEMA_VERSION,
            provider,
            model,
            language,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def run_cached_semantic_request(
    provider: Any,
    *,
    source_hash: str,
    chunk_text: str,
    material_id: str,
    source_start: int,
    source_end: int,
    model: str,
    cache_path: Path,
    validation_source_text: str | None = None,
    language: str = "zh-CN",
    force: bool = False,
    requested_provider: str = "deepseek",
    effective_provider: str = "deepseek",
) -> dict[str, Any]:
    """Run or reuse one semantic request; provider calls are externally visible."""

    chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
    key = semantic_cache_key(
        source_hash=source_hash,
        chunk_hash=chunk_hash,
        provider=effective_provider,
        model=model,
        language=language,
    )
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    cached = cache.get(key)
    if not force and isinstance(cached, dict) and cached.get("validated") is True:
        return {**cached, "cache_hit": True, "cache_key": key}

    response = provider.extract_knowledge_points(
        {
            "material_id": material_id,
            "source_start": source_start,
            "source_end": source_end,
            "source_text": chunk_text,
            "language": language,
        }
    )
    provider_payload = response if isinstance(response, dict) else {"candidates": response}
    validated = validate_candidates(
        provider_payload.get("candidates", provider_payload.get("knowledge_points")),
        material_id=material_id,
        source_text=validation_source_text if validation_source_text is not None else chunk_text,
        section_start=source_start if validation_source_text is not None else None,
        section_end=source_end if validation_source_text is not None else None,
    )
    result = {
        "cache_key": key,
        "cache_hit": False,
        "source_hash": source_hash,
        "chunk_hash": chunk_hash,
        "semantic_pipeline_version": SEMANTIC_PIPELINE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "requested_provider": requested_provider,
        "effective_provider": effective_provider,
        "model": model,
        "language": language,
        "material_id": material_id,
        "source_start": source_start,
        "source_end": source_end,
        "candidates": validated["candidates"],
        "validation_errors": validated["errors"],
        "duplicates_detected": validated["duplicates_detected"],
        "validated": not validated["errors"],
        "cache_write_status": "PENDING",
        "usage": provider_payload.get("usage"),
    }
    if result["validated"]:
        result["cache_write_status"] = "WRITTEN"
        cache[key] = result
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        result["cache_write_status"] = "SKIPPED_INVALID"
    return result
