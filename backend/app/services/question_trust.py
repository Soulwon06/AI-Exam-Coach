"""Deterministic practice-question trust boundary.

This module deliberately does not call OCR, parsers, LLMs, providers, or ranking
code. It only inspects fields already persisted on Question and derives a
fail-closed runtime view for practice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


CHOICE_TYPES = frozenset({"SINGLE_CHOICE", "MULTIPLE_CHOICE"})
TRUE_FALSE_TYPES = frozenset({"TRUE_FALSE"})
OBJECTIVE_TYPES = CHOICE_TYPES | TRUE_FALSE_TYPES

_OPTION_LINE = re.compile(r"^\s*([A-D])\s*[.、．)）:：]\s*(\S.*)\s*$")
_LEADING_ANSWER = re.compile(r"^\s*([A-D](?:\s*[,/、+&]\s*[A-D])*)(?:\s*[.、．)）:：]|\s*$)", re.I)
_STRONG_OBJECTIVE_STEM = re.compile(
    r"（\s*）|\(\s*\)|正确的是|错误的是|不正确的是|说法正确|说法错误|哪一个|哪个|哪项|关键字是|选择题",
    re.I,
)
_WEAK_OBJECTIVE_STEM = re.compile(r"下列|以下|选项|请选择", re.I)
_FRAGMENT_MARKER = re.compile(r"(?:^|\n)\s*(?:YES|TRUE|FALSE|L[0-9]+|SQL-[A-Z-]+|↳)\b", re.I)


@dataclass(frozen=True)
class QuestionTrustAssessment:
    ready: bool
    classification: str
    repairability: str
    confidence: str
    issues: tuple[str, ...]
    objective_signal: bool
    effective_type: str
    runtime_options: tuple[str, ...]
    answer_letters: str
    explanation_quality: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "classification": self.classification,
            "repairability": self.repairability,
            "confidence": self.confidence,
            "issues": list(self.issues),
            "objective_signal": self.objective_signal,
            "effective_type": self.effective_type,
            "runtime_options": list(self.runtime_options),
            "answer_letters": self.answer_letters,
            "explanation_quality": self.explanation_quality,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _evidence_text(question: Any) -> str:
    return "\n".join(
        value
        for value in (_text(getattr(question, "raw_source_text", None)), _text(getattr(question, "effective_question_context", None)))
        if value
    )


def _normalise(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", value or "").upper()


def leading_answer_letters(answer: Any) -> str:
    match = _LEADING_ANSWER.match(_text(answer))
    if not match:
        return ""
    return re.sub(r"[^A-D]", "", match.group(1).upper())


def extract_option_lines(source: Any) -> list[str]:
    """Extract only unambiguous option-shaped lines from persisted text."""

    found: list[tuple[str, str]] = []
    for line in _text(source).splitlines():
        match = _OPTION_LINE.match(line)
        if match:
            found.append((match.group(1).upper(), match.group(2).strip()))
    if len(found) < 2:
        return []
    labels = [label for label, _ in found]
    if len(set(labels)) != len(labels) or labels[0] != "A":
        return []
    # A source boundary is considered safe only when the labels are contiguous
    # and there is no second option block later in the same evidence text.
    expected = [chr(ord("A") + index) for index in range(len(labels))]
    if labels != expected:
        return []
    return [f"{label}. {body}" for label, body in found]


def _valid_options(options: Any) -> tuple[str, ...]:
    if not isinstance(options, (list, tuple)) or len(options) < 2:
        return ()
    result: list[str] = []
    labels: list[str] = []
    for option in options:
        value = _text(option)
        match = _OPTION_LINE.match(value)
        if not match:
            return ()
        labels.append(match.group(1).upper())
        result.append(value)
    if len(set(labels)) != len(labels):
        return ()
    return tuple(result)


def _answer_compatible(answer_letters: str, options: tuple[str, ...]) -> bool:
    if not answer_letters or not options:
        return False
    labels = {option[0].upper() for option in options}
    return all(letter in labels for letter in answer_letters)


def _explanation_quality(explanation: Any, answer: Any) -> str:
    value = _text(explanation)
    if not value:
        return "EXPLANATION_MISSING"
    if _normalise(value) == _normalise(_text(answer)):
        return "EXPLANATION_EQUALS_ANSWER"
    if len(re.sub(r"\s+", "", value)) <= max(3, len(_text(answer))):
        return "EXPLANATION_TRIVIAL"
    if value.startswith("[SOURCE]") or _FRAGMENT_MARKER.search(value):
        return "EXPLANATION_SOURCE_FRAGMENT"
    return "EXPLANATION_GOOD"


def assess_question(question: Any) -> QuestionTrustAssessment:
    content = _text(getattr(question, "content", None))
    stored_type = _text(getattr(question, "type", None)).upper()
    answer = _text(getattr(question, "answer", None))
    persisted_options = _valid_options(getattr(question, "options", None))
    evidence = _evidence_text(question)
    recovered_options = _valid_options(extract_option_lines(evidence))
    runtime_options = persisted_options or recovered_options
    answer_letters = leading_answer_letters(answer)
    strong_stem = bool(_STRONG_OBJECTIVE_STEM.search(content))
    weak_stem = bool(_WEAK_OBJECTIVE_STEM.search(content))
    source_option_lines = extract_option_lines(evidence)
    has_source_options = bool(source_option_lines)
    objective_signal = bool(runtime_options or answer_letters or strong_stem or weak_stem or has_source_options)
    high_confidence_objective = bool(
        runtime_options
        or (answer_letters and (strong_stem or has_source_options))
        or (stored_type in OBJECTIVE_TYPES and (runtime_options or answer_letters))
    )
    confidence = "HIGH" if high_confidence_objective else ("MEDIUM" if objective_signal else "NONE")

    issues: list[str] = []
    if len(content) < 8:
        issues.append("TRUNCATED_STEM")
    elif strong_stem and not runtime_options and not has_source_options:
        issues.append("MISSING_REFERENCED_STATEMENTS")
    if stored_type in CHOICE_TYPES and not persisted_options and not recovered_options:
        issues.append("CHOICE_OPTIONS_MISSING")
    elif stored_type in CHOICE_TYPES and not runtime_options:
        issues.append("MALFORMED_OPTIONS")
    if stored_type not in OBJECTIVE_TYPES and high_confidence_objective:
        issues.append("OBJECTIVE_TYPED_AS_SHORT_ANSWER")
    if has_source_options and not persisted_options:
        issues.append("CHOICE_OPTIONS_IN_RAW_SOURCE_ONLY")
    if answer_letters and not runtime_options:
        issues.append("ANSWER_LETTER_WITHOUT_OPTIONS")
    if answer_letters and runtime_options and not _answer_compatible(answer_letters, runtime_options):
        issues.append("ANSWER_OPTION_MISMATCH")
    if not answer:
        issues.append("MISSING_ANSWER")
    if getattr(question, "image_required", False):
        issues.append("IMAGE_DEPENDENCY")
    if _FRAGMENT_MARKER.search(content):
        issues.append("CONTENT_FRAGMENT")
    explanation_quality = _explanation_quality(getattr(question, "explanation", None), answer)
    if explanation_quality == "EXPLANATION_EQUALS_ANSWER":
        issues.append("EXPLANATION_EQUALS_ANSWER")
    if explanation_quality == "EXPLANATION_MISSING":
        issues.append("EXPLANATION_MISSING")
    if explanation_quality == "EXPLANATION_TRIVIAL":
        issues.append("EXPLANATION_TOO_SHORT_TO_TEACH")

    effective_type = stored_type
    if stored_type not in OBJECTIVE_TYPES and high_confidence_objective and runtime_options and _answer_compatible(answer_letters, runtime_options):
        effective_type = "MULTIPLE_CHOICE" if len(answer_letters) > 1 else "SINGLE_CHOICE"
    if stored_type == "TRUE_FALSE" and not answer_letters and answer.lower() not in {"t", "true", "f", "false", "对", "错", "正确", "错误", "√", "×"}:
        issues.append("ANSWER_OPTION_MISMATCH")

    structural_issues = {
        "TRUNCATED_STEM",
        "MISSING_REFERENCED_STATEMENTS",
        "CHOICE_OPTIONS_MISSING",
        "MALFORMED_OPTIONS",
        "OBJECTIVE_TYPED_AS_SHORT_ANSWER",
        "ANSWER_LETTER_WITHOUT_OPTIONS",
        "ANSWER_OPTION_MISMATCH",
        "MISSING_ANSWER",
        "IMAGE_DEPENDENCY",
    }
    normalised_objective = bool(
        "OBJECTIVE_TYPED_AS_SHORT_ANSWER" in issues
        and effective_type in OBJECTIVE_TYPES
        and runtime_options
        and _answer_compatible(answer_letters, runtime_options)
    )
    blocking_issues = structural_issues - {"OBJECTIVE_TYPED_AS_SHORT_ANSWER"}
    structural_block = bool(blocking_issues.intersection(issues)) or ("OBJECTIVE_TYPED_AS_SHORT_ANSWER" in issues and not normalised_objective)
    recovered = bool(recovered_options and not persisted_options and runtime_options)
    ready = bool(content and not structural_block and (stored_type not in OBJECTIVE_TYPES or effective_type in OBJECTIVE_TYPES))
    if ready and recovered:
        classification = "RECOVERABLE_FROM_PERSISTED_SOURCE"
        repairability = "AUTO_SAFE_REPAIR"
    elif ready:
        classification = "TRUST_READY"
        repairability = "NONE"
    elif "IMAGE_DEPENDENCY" in issues or "TRUNCATED_STEM" in issues or "MISSING_ANSWER" in issues:
        classification = "UNSERVABLE"
        repairability = "DO_NOT_SERVE"
    else:
        classification = "NEEDS_HUMAN_REVIEW"
        repairability = "HUMAN_REVIEW"
    return QuestionTrustAssessment(
        ready=ready,
        classification=classification,
        repairability=repairability,
        confidence=confidence,
        issues=tuple(dict.fromkeys(issues)),
        objective_signal=objective_signal,
        effective_type=effective_type,
        runtime_options=runtime_options,
        answer_letters=answer_letters,
        explanation_quality=explanation_quality,
    )


def is_practice_trust_ready(question: Any) -> bool:
    return assess_question(question).ready


def runtime_question_payload(question: Any) -> dict[str, Any]:
    assessment = assess_question(question)
    source_material = getattr(question, "source_material", None)
    material_name = getattr(source_material, "name", None) or "课程真题"
    return {
        "id": question.id,
        "type": assessment.effective_type,
        "content": question.content,
        "options": list(assessment.runtime_options) if assessment.runtime_options else None,
        "segmentation_status": question.segmentation_status,
        "content_quality": question.content_quality,
        "effective_question_context": question.effective_question_context,
        "is_mapping_eligible": question.is_mapping_eligible,
        "trust_ready": assessment.ready,
        "trust_issues": list(assessment.issues),
        "trust_confidence": assessment.confidence,
        "objective_signal": assessment.objective_signal,
        "explanation_quality": assessment.explanation_quality,
        # Bounded provenance only; raw_source_text is intentionally excluded
        # because it may contain neighboring questions or answer text.
        "exam_year": getattr(question, "exam_year", None),
        "question_number": getattr(question, "question_number", None),
        "source_location": getattr(question, "source_location", None),
        "source_type": getattr(question, "source_type", None),
        "source_material_name": getattr(source_material, "name", None),
        "source_display": {
            "label": material_name,
            "exam_year": getattr(question, "exam_year", None),
            "question_number": getattr(question, "question_number", None),
        },
    }


def trusted_explanation(explanation: Any, answer: Any) -> str | None:
    value = _text(explanation)
    return value if _explanation_quality(value, answer) == "EXPLANATION_GOOD" else None
