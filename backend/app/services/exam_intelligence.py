"""Deterministic Exam Intelligence v1.

REAL_EXAM input is an already persisted ``Material.extracted_text`` value.  This
module never invokes the material parser and never creates StudyUnits.  It only
segments questions, retrieves existing teaching-derived StudyUnits, abstains when
the signal is weak, and persists auditable Question/ExamEvidence records.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app import models


EXAM_INTELLIGENCE_VERSION = "exam-intelligence-v1.2"
TEACHING_TYPES = {"TEXTBOOK", "TEACHER_PPT", "CLASS_NOTES"}
MAPPING_STATUSES = {"MATCHED", "AMBIGUOUS", "UNMATCHED"}
SEGMENTATION_STATUSES = {"PASS", "MERGED_MULTIPLE_QUESTIONS", "SPLIT_INCOMPLETE", "BOUNDARY_UNCERTAIN"}
CONTENT_QUALITY_STATUSES = {
    "PASS", "OCR_NOISY_BUT_USABLE", "SOURCE_TEXT_CORRUPTED",
    "IMAGE_OR_SYMBOL_MISSING", "CONTEXT_MISSING",
}
MAPPING_ELIGIBLE_CONTENT = {"PASS", "OCR_NOISY_BUT_USABLE"}
MAX_RETRIEVAL_K = 5
MATCHED_MIN_SCORE = 0.55
AMBIGUOUS_MIN_SCORE = 0.30
CONTEXT_LOOKBACK_QUESTIONS = 12

_PAGE_RE = re.compile(r"^-+\s*(?:page|image)\s+(.+?)\s*-+$", re.IGNORECASE)
_QUESTION_RE = re.compile(
    r"^\s*(?P<number>\d{1,3})\s*(?:[.．、)）:]\s*|$)(?P<content>.*)$"
)
_QUESTION_WORD_RE = re.compile(
    r"^\s*(?:question|problem|q)\s*(?P<number>\d{1,3})\s*[:.)、-]?\s*(?P<content>.*)$",
    re.IGNORECASE,
)
_SUBQUESTION_RE = re.compile(r"^\s*[（(](?P<number>\d{1,2})[）)]\s*(?P<content>.*)$")
_OPTION_RE = re.compile(r"^\s*(?P<label>[A-Ha-h])\s*(?P<punct>[.．、)）:：])(?P<content>.*)$")
_ANSWER_RE = re.compile(
    r"^\s*(?:答案|正确答案|参考答案|标准答案|正确选项)\s*[:：]?\s*(?P<answer>.+?)\s*$",
    re.IGNORECASE,
)
_PAGE_SCORE_RE = re.compile(r"^\s*(?:总分|标准分|得分|试卷共|考试时间|考试日期|课程名称|授课院|版权所有|收集|制作|通讯|发布于)")
_SECTION_RE = re.compile(r"(?:选择题|单选题|多选题|判断题|填空题|简答题|论述题|计算题|设计题|分析题|语句题|关系代数)")
_FOOTER_RE = re.compile(r"(?:版权所有|收集：|制作：|制作团队介绍|开源资源|公众号|发布于|仅供参考|禁止倒卖)", re.IGNORECASE)
_HARD_STOP_RE = re.compile(r"(?:制作团队介绍|参考文献|references?)", re.IGNORECASE)
_QUESTION_CUE_RE = re.compile(
    r"[?？（）()]|查询|使用|列出|给出|设计|假设|指出|说明|获得|找到|构建|完成|写出|判断|简述|分析|计算|以下|对于|关于",
)
_OCR_GARBAGE_RE = re.compile(r"(?:2050|Foreign Key 实现|以上所有 B B|A B B A)", re.IGNORECASE)
_ANSWER_HEADING_RE = re.compile(r"^\s*(?:答案|参考答案|标准答案|答案解析)\s*(?:[:：].*)?$", re.IGNORECASE)
_STOP_RE = re.compile(r"^\s*(?:参考文献|references?)\s*$", re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "from", "with",
    "is", "are", "be", "by", "as", "using", "use", "query", "find", "give", "show",
    "information", "following", "which", "what", "that", "this", "all", "each", "not",
}
_BILINGUAL_ALIASES = {
    "关系模型": {"relational", "model"}, "关系模式": {"relational", "schema"},
    "关系代数": {"relational", "algebra"}, "sql": {"sql"}, "查询处理": {"query", "processing"},
    "查询优化": {"query", "optimization"}, "完整性约束": {"integrity", "constraint"},
    "实体完整性": {"entity", "integrity"}, "参照完整性": {"referential", "integrity"},
    "函数依赖": {"functional", "dependency", "dependencies"}, "候选码": {"candidate", "key"},
    "主码": {"primary", "key"}, "外码": {"foreign", "key"}, "范式": {"normalization", "normal", "form"},
    "第一范式": {"first", "normal", "form", "1nf"}, "第二范式": {"second", "normal", "form", "2nf"},
    "第三范式": {"third", "normal", "form", "3nf"}, "bc范式": {"bcnf"},
    "事务": {"transaction", "transactions"}, "acid": {"acid"}, "隔离性": {"isolation"},
    "并发控制": {"concurrency", "control"}, "两阶段锁": {"two", "phase", "locking"},
    "死锁": {"deadlock"}, "锁": {"lock", "locking"}, "索引": {"index", "indexing"},
    "b+树": {"b", "tree", "index"}, "哈希索引": {"hash", "index"}, "视图": {"view", "views"},
    "实体联系": {"entity", "relationship"}, "er图": {"entity", "relationship", "er"},
    "两阶段锁协议": {"two", "phase", "lock", "locking", "protocol", "protocols", "based"},
    "可串行调度": {"serializable", "schedule", "schedules"}, "脏读": {"dirty", "read", "reads"},
    "不可重复读": {"nonrepeatable", "read", "reads"}, "幻读": {"phantom", "read", "reads"},
    "散列索引": {"hash", "index", "indexing"}, "查询处理": {"query", "processing", "optimization"},
}


@dataclass
class _SourceLine:
    """Normalized line text plus coordinates in persisted extracted_text."""

    text: str
    location: str | None
    line_index: int
    char_start: int
    char_end: int


@dataclass
class SegmentedQuestion:
    question_number: str
    subquestion_number: str | None
    content: str
    options: list[str]
    answer: str
    source_location: str | None
    raw_source_text: str
    question_type: str
    parent_key: str | None = None
    segmentation_status: str = "PASS"
    content_quality: str = "PASS"
    content_quality_reason: str | None = None
    image_required: bool = False
    segmentation_provenance: dict | None = None


def _normalise(value: str) -> str:
    value = (value or "").replace("\u00a0", " ").replace("？", "?")
    return re.sub(r"\s+", " ", value).strip()


def _is_page_marker(line: str) -> bool:
    return bool(_PAGE_RE.match(_normalise(line)))


def _section_type(line: str) -> str | None:
    value = _normalise(line)
    if "选择" in value or "单选" in value or "多选" in value:
        return "SINGLE_CHOICE" if "多选" not in value else "MULTIPLE_CHOICE"
    if "判断" in value:
        return "TRUE_FALSE"
    if "填空" in value:
        return "FILL_BLANK"
    if "计算" in value:
        return "CALCULATION"
    if "绘图" in value or "ER图" in value.upper():
        return "DRAWING"
    if "设计" in value or "分析" in value or "简答" in value or "论述" in value or "语句" in value or "关系代数" in value:
        return "PROBLEM_SOLVING"
    return None


def _question_start(line: str) -> tuple[str, str] | None:
    value = _normalise(line)
    match = _QUESTION_WORD_RE.match(value)
    if match:
        return match.group("number"), match.group("content").strip()
    match = _QUESTION_RE.match(value)
    if not match:
        return None
    number = match.group("number")
    content = match.group("content").strip()
    # A bare year or score is not a question marker.  Real exams can contain
    # more than 30 questions, so do not use a small arbitrary upper bound.
    if int(number) > 300:
        return None
    return number, content


def _is_noise(line: str) -> bool:
    value = _normalise(line)
    if not value or _is_page_marker(value):
        return True
    if _PAGE_SCORE_RE.match(value) or _FOOTER_RE.search(value):
        return True
    if _ANSWER_HEADING_RE.match(value) or _STOP_RE.match(value):
        return True
    if value in {"请将答案写在此处", "答题说明", "注意事项"}:
        return True
    return False


def _parse_year(text: str, name: str = "") -> int | None:
    match = _YEAR_RE.search((text or "")[:2000]) or _YEAR_RE.search(name or "")
    return int(match.group(1)) if match else None


def _infer_type(section: str | None, options: list[str], content: str) -> str:
    if section:
        return section
    if options:
        return "TRUE_FALSE" if any(re.search(r"正确|错误|对|错|true|false", item, re.I) for item in options) else "SINGLE_CHOICE"
    if re.search(r"SQL|select\b|关系代数|函数依赖|候选码|范式|ER图", content, re.I):
        return "PROBLEM_SOLVING"
    return "OTHER"


def _segmentation_status(raw_text: str, content: str, options: list[str], *, bare_marker: bool) -> str:
    """Classify structural boundary risk without relying on question length."""
    value = _normalise(content)
    raw = _normalise(raw_text)
    score_markers = len(re.findall(r"[（(]\s*\d+\s*分|(?:每题|共)\s*\d+\s*分", value))
    sql_starts = len(re.findall(r"\bselect\b", value, re.IGNORECASE))
    blank_prompts = len(re.findall(r"[（(]\s*[）)]", value))
    embedded_starts = len(re.findall(r"(?:^|\s)\d{1,3}\s*[.．、)）:]\s+", value))
    independent_cues = len(re.findall(
        r"(?:下列|以下|关于|查询|使用.+结构|对于每个|给出以下|完成题目|构建查询)",
        value,
    ))

    # These are strong structural signals for two or more independent blocks,
    # not generic length heuristics.  They cover OCR/PDF line-boundary loss,
    # multiple SQL subquestions, and consecutive MCQs in one extracted block.
    if embedded_starts or score_markers >= 2:
        return "MERGED_MULTIPLE_QUESTIONS"
    if sql_starts >= 2 and (len(value) >= 300 or independent_cues >= 2):
        return "MERGED_MULTIPLE_QUESTIONS"
    if blank_prompts >= 3 and independent_cues >= 2 and len(value) >= 160:
        return "MERGED_MULTIPLE_QUESTIONS"
    if re.search(r"[（(]\s*[A-H]\s+(?:下列|以下|关于|使用|查询)", value, re.IGNORECASE):
        return "MERGED_MULTIPLE_QUESTIONS"
    if bare_marker and not options and (not value or not _QUESTION_CUE_RE.search(value)):
        return "SPLIT_INCOMPLETE"
    if independent_cues >= 3 and len(value) >= 600:
        return "BOUNDARY_UNCERTAIN"
    if raw and not value:
        return "SPLIT_INCOMPLETE"
    return "PASS"


def _content_quality(content: str, options: list[str]) -> tuple[str, str | None, bool]:
    """Assess source fidelity while allowing understandable OCR through."""
    value = _normalise(content)
    image_required = bool(re.search(r"根据上图|如下图|见图|图中|如图所示", value))
    if image_required:
        return "IMAGE_OR_SYMBOL_MISSING", "question refers to an image/diagram not present in the persisted text", True
    if "�" in value or re.search(r"(?:无法识别|缺失图片|图像缺失)", value, re.IGNORECASE):
        return "SOURCE_TEXT_CORRUPTED", "replacement or explicit extraction-loss marker is present", False
    # Formula/OCR damage leaves explanatory scaffolding but removes operands.
    if (
        re.search(r"函数依赖|候选码|闭包|范式", value)
        and (re.search(r"[（(]\s*[,，]|[,{]\s*(?:→|->)|在\s*中[，,]", value) or value.count("、") >= 3)
    ):
        return "SOURCE_TEXT_CORRUPTED", "formula or attribute operands are missing from the source text", False
    if "分解" in value and (
        re.search(r"分解\s*为\s*(?:和|后|，|,)", value) or value.count("分解") >= 2 and value.count("、") >= 2
    ):
        return "SOURCE_TEXT_CORRUPTED", "normalization decomposition operands are missing from the source text", False
    if re.search(r"某-个|I\s*段|飄|弦|溫|示伺|伪¤|[¤§※]", value):
        return "OCR_NOISY_BUT_USABLE", "OCR substitutions are present but the question prompt remains recognizable", False
    if options and "模型" in value and "工具" in value and re.search(r"是一种|直观", value):
        return "OCR_NOISY_BUT_USABLE", "OCR substitutions affect a model/tool prompt but options preserve a usable question", False
    chinese = len(re.findall(r"[\u4e00-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    odd = len(re.findall(r"[^\w\s\u4e00-\u9fff,.!?？！，。；：:()（）\[\]{}+\-*/=<>→←_#'\"%]", value))
    if (len(value) >= 18 and odd / max(1, len(value)) > 0.08) or (latin >= 20 and chinese == 0 and re.search(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}", value) and len(value) < 100):
        return "OCR_NOISY_BUT_USABLE", "OCR noise is present but the question retains a recognizable prompt", False
    if len(value) < 6 or (not options and not re.search(r"[?？。；：:]|查询|说明|计算|判断|构建|关系|事务|锁|索引|范式|SQL|分解|候选码", value, re.IGNORECASE)):
        return "SOURCE_TEXT_CORRUPTED", "question text is too fragmentary to support reliable mapping", False
    return "PASS", None, False


def assess_question_quality(question: SegmentedQuestion) -> dict:
    """Return the deterministic Question Intelligence Quality Gate decision."""
    segmentation_status = question.segmentation_status
    content_quality = question.content_quality
    reason = question.content_quality_reason
    if segmentation_status not in SEGMENTATION_STATUSES:
        segmentation_status = "BOUNDARY_UNCERTAIN"
        reason = "unknown segmentation status"
    if content_quality not in CONTENT_QUALITY_STATUSES:
        content_quality = "SOURCE_TEXT_CORRUPTED"
        reason = "unknown content quality status"
    eligible = segmentation_status == "PASS" and content_quality in MAPPING_ELIGIBLE_CONTENT
    return {
        "segmentation_status": segmentation_status,
        "content_quality": content_quality,
        "content_quality_reason": reason,
        "is_mapping_eligible": eligible,
        "image_required": question.image_required,
    }


def _parse_option_line(line: str) -> tuple[str, str] | None:
    """Parse a line-start option without treating SQL aliases as choices."""
    match = _OPTION_RE.match(line or "")
    if not match:
        return None
    label = match.group("label")
    content = match.group("content").strip()
    if not content:
        return None
    # ``c.Ctyname`` and ``a.column`` are SQL alias expressions.  A lowercase
    # label followed immediately by a dotted identifier is not an option.
    if (
        label.islower()
        and match.group("punct") in {".", "．"}
        and re.match(r"^[A-Za-z_][A-Za-z0-9_$]*", content)
    ):
        return None
    return label.upper(), content


def _finalise_block(number: str, subnumber: str | None, raw: list[_SourceLine], section: str | None, parent_key: str | None, bare_marker: bool = False) -> SegmentedQuestion | None:
    if not raw:
        return None
    options: list[str] = []
    answer = ""
    content_lines: list[str] = []
    for source_line in raw:
        line = source_line.text
        answer_match = _ANSWER_RE.match(_normalise(line))
        if answer_match:
            answer = answer_match.group("answer").strip()
            continue
        if re.match(r"^\s*(?:解析|答案解析|解答过程|解题过程|说明)\s*[:：]", _normalise(line)):
            continue
        if _is_noise(line):
            continue
        option = _parse_option_line(_normalise(line))
        if option:
            label, option_content = option
            options.append(f"{label}. {option_content}")
            continue
        if _SECTION_RE.search(_normalise(line)) and len(_normalise(line)) < 40 and not content_lines:
            continue
        content_lines.append(_normalise(line))
    content = " ".join(content_lines).strip()
    if len(content) < 6:
        return None
    # OCR answer grids often contain bare numbers followed by a run of answer
    # letters.  A bare marker with several question blanks is more likely a
    # merged OCR block than one auditable question; abstain instead of storing it.
    if re.fullmatch(r"(?:[A-Ha-h]|\d+)(?:\s+(?:[A-Ha-h]|\d+))+", content):
        return None
    if bare_marker and len(re.findall(r"[（(]\s*[）)]", content)) > 1:
        return None
    if _OCR_GARBAGE_RE.search(content):
        return None
    if bare_marker and not options and not _QUESTION_CUE_RE.search(content):
        return None
    raw_text = "\n".join(source_line.text for source_line in raw)[:5000]
    location = next((source_line.location for source_line in raw if source_line.location), None)
    segmentation_status = _segmentation_status(raw_text, content, options, bare_marker=bare_marker)
    content_quality, quality_reason, image_required = _content_quality(content, options)
    return SegmentedQuestion(
        question_number=number,
        subquestion_number=subnumber,
        content=content[:2500],
        options=options[:12],
        answer=answer[:500],
        source_location=location,
        raw_source_text=raw_text,
        question_type=_infer_type(section, options, content),
        parent_key=parent_key,
        segmentation_status=segmentation_status,
        content_quality=content_quality,
        content_quality_reason=quality_reason,
        image_required=image_required,
    )


def segment_exam_text(text: str, *, trace_limit: int = 60) -> dict:
    """Split only explicitly numbered question blocks from cached exam text."""
    questions: list[SegmentedQuestion] = []
    trace = {"raw_text_sample": (text or "")[:3000], "blocks": [], "filtered_lines": [], "question_count": 0}
    current: list[_SourceLine] = []
    current_number: str | None = None
    current_sub: str | None = None
    current_parent: str | None = None
    current_bare_marker = False
    section: str | None = None
    section_index: int | None = None
    location: str | None = None
    current_block_start: _SourceLine | None = None
    current_block_end: _SourceLine | None = None
    current_start_reason: str | None = None
    stopped = False

    def flush(end_reason: str = "END_OF_INPUT") -> None:
        nonlocal current, current_number, current_sub, current_parent, current_bare_marker
        nonlocal current_block_start, current_block_end, current_start_reason
        if current_number is not None:
            parsed = _finalise_block(current_number, current_sub, current, section, current_parent, current_bare_marker)
            if parsed:
                parent_candidate_index = None
                if parsed.subquestion_number is not None:
                    parent_candidate_index = next(
                        (index for index in range(len(questions) - 1, -1, -1)
                         if questions[index].question_number == parsed.question_number
                         and questions[index].subquestion_number is None),
                        None,
                    )
                source_locations = []
                seen_locations = set()
                for source_line in current:
                    if source_line.location and source_line.location not in seen_locations:
                        source_locations.append(source_line.location)
                        seen_locations.add(source_line.location)
                missing = []
                if current_block_start is None or current_block_end is None:
                    missing.extend(("line_span", "char_span"))
                if not source_locations:
                    missing.append("source_locations")
                if section is None:
                    missing.append("section")
                if parsed.subquestion_number is not None and parent_candidate_index is None:
                    missing.append("parent_candidate_index")
                provenance = {
                    "schema_version": "segmentation_provenance.v1",
                    "candidate_index": len(questions),
                    "block_index": len(questions),
                    "line_start": current_block_start.line_index if current_block_start else None,
                    "line_end": current_block_end.line_index + 1 if current_block_end else None,
                    "char_start": current_block_start.char_start if current_block_start else None,
                    "char_end": current_block_end.char_end if current_block_end else None,
                    "question_number": parsed.question_number,
                    "subquestion_number": parsed.subquestion_number,
                    "source_locations": source_locations,
                    "section": {"title": section, "index": section_index} if section is not None else None,
                    "parent_candidate_index": parent_candidate_index,
                    "boundary": {
                        "start_reason": current_start_reason or "UNKNOWN",
                        "end_reason": end_reason,
                    },
                    "completeness": "FULL" if not missing else "PARTIAL",
                    "missing": missing,
                }
                parsed = replace(parsed, segmentation_provenance=provenance)
                questions.append(parsed)
                if len(trace["blocks"]) < trace_limit:
                    trace["blocks"].append({
                        "number": parsed.question_number,
                        "subquestion": parsed.subquestion_number,
                        "location": parsed.source_location,
                        "content": parsed.content[:240],
                        "segmentation_status": parsed.segmentation_status,
                        "content_quality": parsed.content_quality,
                        "mapping_eligible": assess_question_quality(parsed)["is_mapping_eligible"],
                        "segmentation_provenance": provenance,
                    })
            elif len(trace["filtered_lines"]) < trace_limit:
                trace["filtered_lines"].append({"number": current_number, "reason": "empty-or-noisy-question-block"})
        current = []
        current_number = None
        current_sub = None
        current_parent = None
        current_bare_marker = False
        current_block_start = None
        current_block_end = None
        current_start_reason = None

    char_offset = 0
    for line_index, raw_line in enumerate((text or "").splitlines(keepends=True)):
        source_line = _SourceLine(
            text=_normalise(raw_line),
            location=location,
            line_index=line_index,
            char_start=char_offset,
            char_end=char_offset + len(raw_line),
        )
        char_offset += len(raw_line)
        line = source_line.text
        page = _PAGE_RE.match(line)
        if page:
            if current_number is not None:
                current_block_end = source_line
            location = page.group(1).strip()
            continue
        if _HARD_STOP_RE.search(line) or _STOP_RE.match(line):
            if current_number is not None:
                current_block_end = source_line
            flush("HARD_STOP")
            stopped = True
            continue
        if stopped:
            continue
        new_section = _section_type(line)
        if new_section:
            if current_number is not None:
                current_block_end = source_line
            flush("SECTION_CHANGE")
            section_index = (section_index + 1) if section_index is not None else 0
            section = new_section
            continue
        sub = _SUBQUESTION_RE.match(line)
        if sub and current_number is not None:
            parent_number = current_parent or current_number
            flush("SUBQUESTION_BOUNDARY")
            current_number = parent_number
            current_sub = sub.group("number")
            current_parent = current_number
            current_bare_marker = not bool(sub.group("content").strip())
            current_block_start = source_line
            current_block_end = source_line
            current_start_reason = "SUBQUESTION_BOUNDARY"
            current = [_SourceLine(sub.group("content"), location, source_line.line_index, source_line.char_start, source_line.char_end)] if sub.group("content") else []
            continue
        start = _question_start(line)
        if start:
            flush("QUESTION_BOUNDARY")
            current_number, first_content = start
            current_sub = None
            current_parent = current_number
            current_bare_marker = not bool(first_content)
            current_block_start = source_line
            current_block_end = source_line
            current_start_reason = "QUESTION_START"
            current = [_SourceLine(first_content, location, source_line.line_index, source_line.char_start, source_line.char_end)] if first_content else []
            continue
        if current_number is not None:
            current.append(source_line)
            current_block_end = source_line
        elif line and len(trace["filtered_lines"]) < trace_limit and (_is_noise(line) or re.fullmatch(r"[A-H](?:\s+[A-H])+", line)):
            trace["filtered_lines"].append({"line": line[:240], "reason": "exam-metadata-or-answer-noise"})
    flush("END_OF_INPUT")
    trace["question_count"] = len(questions)
    return {"questions": questions, "exam_year": _parse_year(text), "trace": trace}


def _norm_for_fingerprint(value: str) -> str:
    value = re.sub(r"\s+", "", (value or "").casefold())
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value)


def question_fingerprint(material_id: str, question: SegmentedQuestion) -> str:
    raw = "|".join((material_id, question.question_number, question.subquestion_number or "", _norm_for_fingerprint(question.content)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    value = (value or "").casefold()
    words = {item for item in re.findall(r"[a-z][a-z0-9+#]*|\d+[a-z]*", value) if item not in _STOPWORDS and len(item) > 1}
    cjk = re.findall(r"[\u4e00-\u9fff]+", value)
    for chunk in cjk:
        words.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    for alias, terms in _BILINGUAL_ALIASES.items():
        if alias.casefold() in value:
            words.update(terms)
    return words


def _unit_text(unit: models.StudyUnit) -> str:
    return " ".join(filter(None, (unit.canonical_name, unit.title, unit.description, unit.source_excerpt)))


def retrieve_candidates(question: SegmentedQuestion | str, units: Iterable[models.StudyUnit], top_k: int = 5) -> list[dict]:
    top_k = max(1, min(MAX_RETRIEVAL_K, top_k))
    question_text = question.content if isinstance(question, SegmentedQuestion) else str(question)
    q_tokens = _tokens(question_text)
    ranked: list[dict] = []
    for unit in units:
        title = unit.canonical_name or unit.title
        candidate_text = _unit_text(unit)
        title_tokens = _tokens(title)
        u_tokens = _tokens(candidate_text)
        overlap = len(q_tokens & title_tokens) / max(1, len(title_tokens))
        reverse_overlap = len(q_tokens & title_tokens) / max(1, len(q_tokens))
        phrase = SequenceMatcher(None, _norm_for_fingerprint(question_text), _norm_for_fingerprint(title)).ratio()
        signals: list[str] = []
        if overlap > 0:
            signals.append(f"token-overlap:{overlap:.2f}")
        if reverse_overlap > 0:
            signals.append(f"question-signal:{reverse_overlap:.2f}")
        if phrase >= 0.45:
            signals.append(f"title-similarity:{phrase:.2f}")
        alias_match = 0.0
        for alias, alias_tokens in _BILINGUAL_ALIASES.items():
            if alias.casefold() in question_text.casefold():
                matched = len(alias_tokens & (title_tokens | u_tokens))
                if matched:
                    alias_match = max(alias_match, matched / len(alias_tokens), 0.6)
                    signals.append(f"bilingual-alias:{alias}")
        score = min(1.0, 0.45 * reverse_overlap + 0.25 * overlap + 0.15 * phrase + 0.35 * alias_match)
        if not signals:
            continue
        ranked.append({"study_unit_id": unit.id, "canonical_name": title, "retrieval_score": round(score, 4), "reason": signals})
    ranked.sort(key=lambda item: (-item["retrieval_score"], item["canonical_name"] or "", item["study_unit_id"]))
    return ranked[:top_k]


def validate_mapping_result(result: dict, valid_unit_ids: set[str]) -> dict:
    status = result.get("status")
    if status not in MAPPING_STATUSES:
        raise ValueError(f"invalid mapping status: {status}")
    primary = result.get("primary")
    secondary = list(result.get("secondary") or [])
    if primary and primary.get("study_unit_id") not in valid_unit_ids:
        raise ValueError("primary references an unknown StudyUnit")
    if len([item for item in [primary] if item]) > 1:
        raise ValueError("mapping has more than one primary")
    for item in secondary:
        if item.get("study_unit_id") not in valid_unit_ids:
            raise ValueError("secondary references an unknown StudyUnit")
    if primary and any(item.get("study_unit_id") == primary.get("study_unit_id") for item in secondary):
        raise ValueError("primary duplicated as secondary")
    return {"status": status, "primary": primary, "secondary": secondary}


def map_question(question: SegmentedQuestion, units: list[models.StudyUnit], *, top_k: int = 5) -> dict:
    candidates = retrieve_candidates(question, units, top_k=top_k)
    if not candidates:
        return {"status": "UNMATCHED", "confidence": 0.0, "primary": None, "secondary": [], "candidates": []}
    top = candidates[0]
    second_score = candidates[1]["retrieval_score"] if len(candidates) > 1 else 0.0
    gap = top["retrieval_score"] - second_score
    if top["retrieval_score"] < AMBIGUOUS_MIN_SCORE:
        status = "UNMATCHED"
    elif top["retrieval_score"] >= MATCHED_MIN_SCORE and gap >= 0.12:
        status = "MATCHED"
    else:
        status = "AMBIGUOUS"
    primary = top if status == "MATCHED" else None
    secondary = []
    if status == "MATCHED":
        secondary = [item for item in candidates[1:] if item["retrieval_score"] >= 0.45 and item["retrieval_score"] >= top["retrieval_score"] - 0.25][:3]
    return {"status": status, "confidence": round(top["retrieval_score"], 4), "primary": primary, "secondary": secondary, "candidates": candidates}


def _teaching_units(db: Session, course_id: str) -> list[models.StudyUnit]:
    return (
        db.query(models.StudyUnit)
        .filter(
            models.StudyUnit.course_id == course_id,
            models.StudyUnit.source_type.in_(TEACHING_TYPES),
            models.StudyUnit.canonical_name.isnot(None),
        )
        .order_by(models.StudyUnit.created_at.asc())
        .all()
    )


_CONTEXT_REFERENCE_RE = re.compile(r"(?:第\s*|题目\s*|问题\s*)(\d{1,3})\s*题?")
_CONTEXT_WORD_RE = re.compile(r"上一题|上题|前题|上述|前述|根据上图|如下图|见图|对于上述关系|完成上一题|完成题目")


def _context_parent_number(item: SegmentedQuestion, previous_numbers: list[str]) -> str | None:
    if item.subquestion_number and item.parent_key:
        return str(item.parent_key)
    match = _CONTEXT_REFERENCE_RE.search(item.content or "")
    if match:
        referenced = str(int(match.group(1)))
        if referenced != str(item.question_number):
            return referenced
    if _CONTEXT_WORD_RE.search(item.content or "") and previous_numbers:
        return previous_numbers[-1]
    return None


def _context_dependent(item: SegmentedQuestion) -> bool:
    return bool(_CONTEXT_REFERENCE_RE.search(item.content or "") or _CONTEXT_WORD_RE.search(item.content or "") or item.subquestion_number)


def _nearest_prior_question(
    previous_questions: list[models.Question], parent_number: str | None,
) -> models.Question | None:
    """Resolve only against a bounded, prior segment of the current material.

    Question numbers can restart in later exam blocks.  A first-seen global
    number map therefore has no reliable scope.  The current segmentation
    stream does not persist a section/group identity, so nearest prior context
    is the strongest structural signal available without expanding the schema.
    """
    if not parent_number:
        return None
    for candidate in reversed(previous_questions[-CONTEXT_LOOKBACK_QUESTIONS:]):
        if (
            str(candidate.question_number or "") == str(parent_number)
            and candidate.subquestion_number is None
        ):
            return candidate
    return None


def _invalidate_derived_mappings(db: Session, question_id: str, reason: str) -> None:
    """Keep derived rows for audit, but make them invisible to downstream use."""
    for link in db.query(models.QuestionStudyUnit).filter(models.QuestionStudyUnit.question_id == question_id).all():
        link.is_active = False
        link.invalidated_reason = reason
    for evidence in db.query(models.ExamEvidence).filter(models.ExamEvidence.question_id == question_id).all():
        evidence.is_active = False
        evidence.invalidated_reason = reason


def _active_question_links(db: Session, question_id: str) -> list[models.QuestionStudyUnit]:
    return db.query(models.QuestionStudyUnit).filter(
        models.QuestionStudyUnit.question_id == question_id,
        models.QuestionStudyUnit.is_active.isnot(False),
    ).all()


def _persist_question(
    db: Session,
    material: models.Material,
    item: SegmentedQuestion,
    year: int | None,
    units: list[models.StudyUnit],
    previous_questions: list[models.Question] | None = None,
    run_mapping: bool = True,
) -> tuple[models.Question, dict, bool]:
    fingerprint = question_fingerprint(material.id, item)
    question = db.query(models.Question).filter(models.Question.fingerprint == fingerprint).first()
    created = question is None
    if question is None:
        question = models.Question(course_id=material.course_id, source_type="REAL_EXAM", content=item.content, answer=item.answer or "")
    question.course_id = material.course_id
    question.source_type = "REAL_EXAM"
    question.type = item.question_type
    question.content = item.content
    question.options = item.options or None
    question.answer = item.answer or ""
    question.source_material_id = material.id
    question.exam_year = year
    question.question_number = item.question_number
    question.subquestion_number = item.subquestion_number
    question.source_location = item.source_location
    question.raw_source_text = item.raw_source_text
    question.extraction_method = material.parser_method
    question.extraction_version = EXAM_INTELLIGENCE_VERSION
    question.fingerprint = fingerprint
    mapping = map_question(item, units) if run_mapping else {
        "status": question.mapping_status if not created else "PENDING",
        "confidence": question.mapping_confidence if not created else None,
        "primary": None, "secondary": [], "candidates": [],
    }
    if run_mapping or created:
        question.mapping_status = mapping["status"]
        question.mapping_confidence = mapping["confidence"]
        question.mapping_method = "deterministic_lexical" if run_mapping else None
        question.mapping_version = EXAM_INTELLIGENCE_VERSION if run_mapping else None
    quality = assess_question_quality(item)
    question.segmentation_status = quality["segmentation_status"]
    question.content_quality = quality["content_quality"]
    question.content_quality_reason = quality["content_quality_reason"]
    if created:
        question.segmentation_provenance = item.segmentation_provenance
    question.effective_question_context = None
    question.image_required = quality["image_required"]
    question.segmentation_is_current = True

    previous_questions = previous_questions or []
    previous_numbers = [str(previous.question_number or "") for previous in previous_questions]
    parent_number = _context_parent_number(item, previous_numbers)
    parent = _nearest_prior_question(previous_questions, parent_number)
    if parent is not None and parent.id != question.id:
        question.parent_question_id = parent.id
        question.effective_question_context = f"{parent.content}\n当前题目：{item.content}"[:5000]
    elif _context_dependent(item):
        question.parent_question_id = None
        if question.content_quality in {"PASS", "OCR_NOISY_BUT_USABLE"}:
            question.content_quality = "CONTEXT_MISSING"
            question.content_quality_reason = "question references prior/shared context that could not be restored"

    eligible = question.segmentation_status == "PASS" and question.content_quality in MAPPING_ELIGIBLE_CONTENT
    question.is_mapping_eligible = eligible
    if run_mapping and eligible:
        mapping_item = replace(item, content=question.effective_question_context or item.content)
        mapping = map_question(mapping_item, units)
    elif run_mapping:
        mapping = {
            "status": "UNMATCHED", "confidence": 0.0, "primary": None,
            "secondary": [], "candidates": [], "quality_gate": quality,
        }
    db.add(question)
    db.flush()
    if run_mapping:
        _invalidate_derived_mappings(db, question.id, "quality_gate_refresh")
    if run_mapping and eligible and mapping["status"] == "MATCHED" and mapping["primary"]:
        selected = [(mapping["primary"], True)] + [(candidate, False) for candidate in mapping["secondary"]]
        for candidate, is_primary in selected:
            unit = next((u for u in units if u.id == candidate["study_unit_id"]), None)
            if unit is None:
                raise ValueError("mapping selected a StudyUnit outside the candidate pool")
            link = db.query(models.QuestionStudyUnit).filter(
                models.QuestionStudyUnit.question_id == question.id,
                models.QuestionStudyUnit.study_unit_id == unit.id,
            ).first()
            if link is None:
                link = models.QuestionStudyUnit(question_id=question.id, study_unit_id=unit.id)
                db.add(link)
            link.is_primary = is_primary
            link.relevance_score = candidate["retrieval_score"]
            link.is_active = True
            link.invalidated_reason = None
            evidence = db.query(models.ExamEvidence).filter(
                models.ExamEvidence.question_id == question.id,
                models.ExamEvidence.study_unit_id == unit.id,
            ).order_by(models.ExamEvidence.created_at.asc()).first()
            if evidence is None:
                evidence = models.ExamEvidence(
                    question_id=question.id, source_material_id=material.id,
                    study_unit_id=unit.id,
                )
                db.add(evidence)
            evidence.source_material_id = material.id
            evidence.exam_year = year
            evidence.is_primary = is_primary
            evidence.relevance_score = candidate["retrieval_score"]
            evidence.confidence = mapping["confidence"]
            evidence.source_location = item.source_location
            evidence.mapping_method = "deterministic_lexical"
            evidence.mapping_version = EXAM_INTELLIGENCE_VERSION
            evidence.is_active = True
            evidence.invalidated_reason = None
    elif run_mapping:
        question.mapping_method = "quality_gate"
    return question, mapping, created


def process_exam_material(
    db: Session,
    material: models.Material,
    *,
    persist: bool = True,
    run_mapping: bool = True,
) -> dict:
    """Process only cached text for one REAL_EXAM material.

    This is intentionally separate from ``parse_material``.  Calling it is a
    regression guard: no PDF/DOCX parser or OCR function is reachable here.
    """
    if material.type != "REAL_EXAM":
        raise ValueError("Exam Intelligence accepts REAL_EXAM materials only")
    if material.parsing_status not in {"PARSED", "LOW_QUALITY"} or not material.extracted_text:
        return {"status": "FAILED", "reason": "REAL_EXAM has no usable persisted extracted_text", "questions": [], "created_count": 0, "reused_count": 0, "parser_calls": 0}
    segmented = segment_exam_text(material.extracted_text)
    units = _teaching_units(db, material.course_id)
    year = segmented["exam_year"] or _parse_year(material.extracted_text, material.name)
    persisted = []
    created_count = 0
    reused_count = 0
    previous_questions: list[models.Question] = []
    current_fingerprints: set[str] = set()
    if persist:
        for item in segmented["questions"]:
            question, mapping, created = _persist_question(
                db, material, item, year, units, previous_questions, run_mapping=run_mapping
            )
            persisted.append((question, mapping, created))
            created_count += int(created)
            reused_count += int(not created)
            current_fingerprints.add(question.fingerprint)
            previous_questions.append(question)
        # Older runs may have persisted a block that the current structural
        # parser no longer emits.  Keep the record and its evidence for audit,
        # but prevent it from entering mapping/practice as a trusted question.
        stale_questions = db.query(models.Question).filter(
            models.Question.source_material_id == material.id,
            models.Question.extraction_version == EXAM_INTELLIGENCE_VERSION,
        ).all()
        for stale in stale_questions:
            if stale.fingerprint not in current_fingerprints:
                stale.segmentation_status = "SPLIT_INCOMPLETE"
                stale.content_quality_reason = "question was not present in the latest structural segmentation"
                stale.is_mapping_eligible = False
                stale.segmentation_is_current = False
                _invalidate_derived_mappings(db, stale.id, "quality_gate_stale_segmentation")
        db.flush()
    return {
        "status": "COMPLETED", "material_id": material.id, "exam_year": year,
        "questions": segmented["questions"], "persisted": persisted,
        "created_count": created_count, "reused_count": reused_count,
        "duplicate_count": 0, "parser_calls": 0, "ocr_calls": 0,
        "quality_gate": {
            "eligible_questions": sum(int(item[0].is_mapping_eligible is True) for item in persisted),
            "ineligible_questions": sum(int(item[0].is_mapping_eligible is not True) for item in persisted),
        },
        "trace": segmented["trace"], "candidate_unit_count": len(units),
    }


def _refresh_quality_for_existing_questions(db: Session, course_id: str) -> dict:
    """Backfill gate fields from persisted Question text without re-segmentation I/O.

    This covers questions written by older Exam Intelligence versions.  It does
    not rerun retrieval or rewrite their original content; it only records the
    gate decision and invalidates derived rows when the persisted block is not
    safe for automatic mapping.
    """
    questions = db.query(models.Question).filter(
        models.Question.course_id == course_id,
        models.Question.source_type == "REAL_EXAM",
    ).order_by(models.Question.source_material_id.asc(), models.Question.created_at.asc()).all()
    previous_by_material: dict[str, list[models.Question]] = {}
    counts = Counter()
    backfilled_questions = 0
    for question in questions:
        if question.segmentation_is_current is True and question.segmentation_status and question.content_quality:
            counts["eligible" if question.is_mapping_eligible is True else "ineligible"] += 1
            if question.question_number:
                previous_by_material.setdefault(question.source_material_id or "", []).append(question)
            continue
        item = SegmentedQuestion(
            question_number=question.question_number or "", subquestion_number=question.subquestion_number,
            content=question.content or "", options=question.options or [], answer=question.answer or "",
            source_location=question.source_location, raw_source_text=question.raw_source_text or question.content or "",
            question_type=question.type,
            parent_key=question.question_number if question.subquestion_number else None,
        )
        item.segmentation_status = _segmentation_status(item.raw_source_text, item.content, item.options, bare_marker=False)
        item.content_quality, item.content_quality_reason, item.image_required = _content_quality(item.content, item.options)
        backfilled_questions += 1
        prior = previous_by_material.setdefault(question.source_material_id or "", [])
        parent_number = _context_parent_number(
            item, [str(previous.question_number or "") for previous in prior]
        )
        parent = _nearest_prior_question(prior, parent_number)
        if parent is not None and parent.id != question.id:
            question.parent_question_id = parent.id
            question.effective_question_context = f"{parent.content}\n当前题目：{question.content}"[:5000]
        elif _context_dependent(item) and question.content_quality in MAPPING_ELIGIBLE_CONTENT:
            question.content_quality = "CONTEXT_MISSING"
            question.content_quality_reason = "question references prior/shared context that could not be restored"
        question.segmentation_status = item.segmentation_status
        if parent is not None and parent.id != question.id:
            question.content_quality = item.content_quality
            question.content_quality_reason = item.content_quality_reason
        elif question.content_quality != "CONTEXT_MISSING":
            question.content_quality = item.content_quality
            question.content_quality_reason = item.content_quality_reason
        question.image_required = item.image_required
        question.is_mapping_eligible = question.segmentation_status == "PASS" and question.content_quality in MAPPING_ELIGIBLE_CONTENT
        question.segmentation_is_current = False
        if question.is_mapping_eligible is not True:
            _invalidate_derived_mappings(db, question.id, "quality_gate_legacy_question")
        counts["eligible" if question.is_mapping_eligible is True else "ineligible"] += 1
        if question.question_number:
            prior.append(question)
    return {
        "eligible_questions": counts["eligible"],
        "ineligible_questions": counts["ineligible"],
        "backfilled_questions": backfilled_questions,
    }


def process_cached_exams(db: Session, course_id: str) -> dict:
    materials = (
        db.query(models.Material)
        .filter(models.Material.course_id == course_id, models.Material.type == "REAL_EXAM")
        .order_by(models.Material.created_at.asc())
        .all()
    )
    original_text = {material.id: material.extracted_text for material in materials}
    results = []
    for material in materials:
        result = process_exam_material(db, material)
        question_samples = []
        for question, mapping, _ in result.get("persisted", [])[:200]:
            question_samples.append({
                "question_id": question.id,
                "question_number": question.question_number,
                "subquestion_number": question.subquestion_number,
                "source_location": question.source_location,
                "content": (question.content or "")[:240],
                "segmentation_status": question.segmentation_status,
                "content_quality": question.content_quality,
                "content_quality_reason": question.content_quality_reason,
                "segmentation_provenance": question.segmentation_provenance,
                "effective_question_context": (question.effective_question_context or "")[:240] or None,
                "is_mapping_eligible": question.is_mapping_eligible,
                "status": mapping.get("status"),
                "confidence": mapping.get("confidence"),
                "candidates": mapping.get("candidates", [])[:MAX_RETRIEVAL_K],
            })
        results.append({
            "material_id": material.id,
            "material_name": material.name,
            "status": result.get("status"),
            "exam_year": result.get("exam_year"),
            "question_count": len(result.get("questions") or []),
            "created_count": result.get("created_count", 0),
            "reused_count": result.get("reused_count", 0),
            "duplicate_count": result.get("duplicate_count", 0),
            "parser_calls": result.get("parser_calls", 0),
            "ocr_calls": result.get("ocr_calls", 0),
            "quality_gate": result.get("quality_gate", {}),
            "candidate_unit_count": result.get("candidate_unit_count", 0),
            "trace": result.get("trace", {}),
            "question_samples": question_samples,
            "reason": result.get("reason"),
        })
    legacy_quality = _refresh_quality_for_existing_questions(db, course_id)
    db.flush()
    extracted_text_mutation_count = sum(
        int(original_text.get(material.id) != material.extracted_text)
        for material in materials
    )
    return {
        "course_id": course_id, "material_count": len(materials), "results": results,
        "parser_calls": sum(item.get("parser_calls", 0) for item in results),
        "ocr_calls": sum(item.get("ocr_calls", 0) for item in results),
        "extracted_text_mutation_count": extracted_text_mutation_count,
        "quality_gate": {
            "eligible_questions": legacy_quality["eligible_questions"],
            "ineligible_questions": legacy_quality["ineligible_questions"],
            "backfilled_questions": legacy_quality["backfilled_questions"],
        },
    }


def build_candidate_dataset(db: Session, course_id: str, limit: int = 20) -> dict:
    """Create review candidates without inventing expected labels."""
    questions = (
        db.query(models.Question)
        .filter(
            models.Question.course_id == course_id,
            models.Question.source_type == "REAL_EXAM",
            models.Question.extraction_version == EXAM_INTELLIGENCE_VERSION,
        )
        .order_by(models.Question.created_at.asc())
        .limit(limit)
        .all()
    )
    cases = []
    for question in questions:
        stable_id = question.fingerprint or question.id
        cases.append({
            "case_id": f"EXAM-{stable_id[:16]}", "label_status": "NEEDS_HUMAN_REVIEW",
            "question_id": question.id, "source_material_id": question.source_material_id,
            "fingerprint": question.fingerprint,
            "question_number": question.question_number, "subquestion_number": question.subquestion_number,
            "source_location": question.source_location, "source_type": question.source_type,
            "question": question.content[:2500], "expected_primary": [], "expected_secondary": [],
        })
    return {
        "schema_version": "exam-ground-truth-v2", "course_id": course_id,
        "segmentation_annotations": [], "cases": cases,
    }


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _annotation_list(dataset: dict) -> list[dict]:
    raw = dataset.get("segmentation_annotations") or dataset.get("segmentation") or []
    if isinstance(raw, dict):
        result = []
        for material_id, annotation in raw.items():
            if isinstance(annotation, dict):
                item = dict(annotation)
                item.setdefault("source_material_id", material_id)
                result.append(item)
        return result
    return [dict(item) for item in raw if isinstance(item, dict)]


def _expected_identities(annotation: dict) -> list[dict]:
    raw = annotation.get("expected_question_identities")
    if raw is None:
        raw = annotation.get("expected_questions")
    if raw is None:
        raw = annotation.get("expected_question_numbers")
    if not isinstance(raw, list):
        return []
    identities = []
    for value in raw:
        if isinstance(value, dict):
            identities.append(dict(value))
        elif value is not None:
            identities.append({"question_number": str(value)})
    return identities


def _identity_matches(expected: dict, question: models.Question) -> bool:
    if expected.get("question_id") and str(expected["question_id"]) == str(question.id):
        return True
    if expected.get("fingerprint") and str(expected["fingerprint"]) == str(question.fingerprint):
        return True
    if expected.get("source_material_id") and expected["source_material_id"] != question.source_material_id:
        return False
    if expected.get("question_number") is not None and str(expected["question_number"]) != str(question.question_number):
        return False
    if expected.get("subquestion_number") is not None and str(expected["subquestion_number"]) != str(question.subquestion_number):
        return False
    if expected.get("source_location") and expected["source_location"] != question.source_location:
        return False
    return any(key in expected for key in ("question_number", "subquestion_number", "source_location"))


def _question_number_annotations(dataset: dict) -> list[dict]:
    raw = dataset.get("question_number_annotations") or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _failure_record(case: dict, question: models.Question | None, predicted: dict, failure_type: str) -> dict:
    return {
        "case_id": case.get("case_id"),
        "question": case.get("question", ""),
        "source_material_id": (question.source_material_id if question is not None else case.get("source_material_id")),
        "source_location": (question.source_location if question is not None else case.get("source_location")),
        "expected_primary": case.get("expected_primary") or [],
        "expected_secondary": case.get("expected_secondary") or [],
        "expected_status": case.get("expected_status"),
        "predicted_primary": predicted.get("primary"),
        "predicted_secondary": predicted.get("secondary", []),
        "predicted_status": predicted.get("status"),
        "confidence": predicted.get("confidence"),
        "retrieved_top5": predicted.get("candidates", [])[:MAX_RETRIEVAL_K],
        "failure_type": failure_type,
    }


def _mapping_metrics_for_cases(db: Session, cases: list[dict], units: list[models.StudyUnit], *, eligible_only: bool = False) -> dict:
    """Compute mapping metrics for an explicit population of Question rows."""
    selected: list[tuple[dict, models.Question]] = []
    for case in cases:
        question = db.get(models.Question, case.get("question_id"))
        if question is None or (eligible_only and question.is_mapping_eligible is not True):
            continue
        selected.append((case, question))
    valid_unit_ids = {unit.id for unit in units}
    top_hits = {1: 0, 3: 0, 5: 0}
    primary_hits = 0
    secondary_tp = secondary_fp = secondary_fn = 0
    high_conf_total = high_conf_correct = false_high_confidence = 0
    forced_mapping = 0
    status_counts = Counter()
    status_correct = Counter()

    for case, question in selected:
        content = question.effective_question_context or question.content
        item = SegmentedQuestion(
            question_number=question.question_number or "", subquestion_number=question.subquestion_number,
            content=content, options=question.options or [], answer=question.answer or "",
            source_location=question.source_location, raw_source_text=question.raw_source_text or "",
            question_type=question.type,
        )
        retrieved = retrieve_candidates(item, units)
        links = _active_question_links(db, question.id)
        primary = next((link.study_unit_id for link in links if link.is_primary), None)
        secondary = [link.study_unit_id for link in links if not link.is_primary]
        expected_primary = case.get("expected_primary") or []
        if isinstance(expected_primary, str):
            expected_primary = [expected_primary]
        expected = expected_primary[0] if expected_primary else None
        if expected:
            candidate_ids = [candidate["study_unit_id"] for candidate in retrieved]
            for k in top_hits:
                top_hits[k] += int(expected in candidate_ids[:k])
            primary_hits += int(primary == expected)
            expected_secondary = set(case.get("expected_secondary") or [])
            predicted_secondary = set(secondary)
            secondary_tp += len(expected_secondary & predicted_secondary)
            secondary_fp += len(predicted_secondary - expected_secondary)
            secondary_fn += len(expected_secondary - predicted_secondary)
            if question.mapping_confidence is not None and question.mapping_confidence >= MATCHED_MIN_SCORE:
                high_conf_total += 1
                high_conf_correct += int(primary == expected)
                false_high_confidence += int(primary != expected)
        expected_status = case.get("expected_status")
        if expected_status:
            status_counts[expected_status] += 1
            status_correct[expected_status] += int(question.mapping_status == expected_status)
            forced_mapping += int(expected_status != "MATCHED" and question.mapping_status == "MATCHED")

    secondary_precision = _safe_rate(secondary_tp, secondary_tp + secondary_fp)
    secondary_recall = _safe_rate(secondary_tp, secondary_tp + secondary_fn)
    return {
        "reviewed_cases": len(selected),
        "top_1_recall": _safe_rate(top_hits[1], len(selected)) if selected else None,
        "top_3_recall": _safe_rate(top_hits[3], len(selected)) if selected else None,
        "top_5_recall": _safe_rate(top_hits[5], len(selected)) if selected else None,
        "primary_top_1_accuracy": _safe_rate(primary_hits, len(selected)) if selected else None,
        "secondary_precision": secondary_precision if selected else None,
        "secondary_recall": secondary_recall if selected else None,
        "secondary_f1": _safe_rate(2 * secondary_precision * secondary_recall, secondary_precision + secondary_recall) if secondary_precision is not None and secondary_recall is not None and secondary_precision + secondary_recall else None,
        "high_confidence_accuracy": _safe_rate(high_conf_correct, high_conf_total),
        "false_high_confidence_rate": _safe_rate(false_high_confidence, high_conf_total),
        "forced_mapping_rate": _safe_rate(forced_mapping, sum(status_counts.values())) if status_counts else None,
        "ambiguous_correctness": _safe_rate(status_correct["AMBIGUOUS"], status_counts["AMBIGUOUS"]) if status_counts["AMBIGUOUS"] else None,
        "unmatched_correctness": _safe_rate(status_correct["UNMATCHED"], status_counts["UNMATCHED"]) if status_counts["UNMATCHED"] else None,
    }


def evaluate_dataset(db: Session, dataset: dict) -> dict:
    cases = dataset.get("cases") or []
    reviewed = [case for case in cases if case.get("label_status") == "REVIEWED" and not case.get("stale")]
    predictions = {}
    units = _teaching_units(db, dataset.get("course_id", ""))
    valid_unit_ids = {unit.id for unit in units}
    failure_breakdown = Counter()
    top_failure_cases = []
    seen_failures = set()

    def add_failure(case: dict, question: models.Question | None, predicted: dict, failure_type: str) -> None:
        key = (case.get("case_id"), failure_type)
        if key in seen_failures:
            return
        seen_failures.add(key)
        failure_breakdown[failure_type] += 1
        top_failure_cases.append(_failure_record(case, question, predicted, failure_type))

    top_hits = {1: 0, 3: 0, 5: 0}
    primary_hits = 0
    secondary_tp = secondary_fp = secondary_fn = 0
    high_conf_total = high_conf_correct = false_high_confidence = 0
    forced_mapping = ambiguous_correct = unmatched_correct = 0
    status_cases = 0
    question_number_hits = question_number_total = 0
    provenance_hits = provenance_total = 0
    for case in reviewed:
        question = db.get(models.Question, case.get("question_id"))
        if question is None:
            add_failure(case, None, {"status": "MISSING", "candidates": []}, "PROVENANCE_ERROR")
            continue
        item = SegmentedQuestion(
            question_number=question.question_number or "", subquestion_number=question.subquestion_number,
            content=question.effective_question_context or question.content, options=question.options or [], answer=question.answer or "",
            source_location=question.source_location, raw_source_text=question.raw_source_text or "",
            question_type=question.type,
        )
        retrieved = retrieve_candidates(item, units)
        links = _active_question_links(db, question.id)
        primary = next((link.study_unit_id for link in links if link.is_primary), None)
        secondary = [link.study_unit_id for link in links if not link.is_primary]
        predictions[case["case_id"]] = {"primary": primary, "secondary": secondary, "status": question.mapping_status, "confidence": question.mapping_confidence, "candidates": retrieved}
        predicted = predictions[case["case_id"]]
        invalid_link = any(link.study_unit_id not in valid_unit_ids for link in links)
        if invalid_link:
            add_failure(case, question, predicted, "INVALID_MAPPING")
        expected_primary = case.get("expected_primary") or []
        if isinstance(expected_primary, str):
            expected_primary = [expected_primary]
        expected = expected_primary[0] if expected_primary else None
        candidate_ids = [candidate["study_unit_id"] for candidate in retrieved]
        if expected:
            for k in top_hits:
                top_hits[k] += int(expected in candidate_ids[:k])
            primary_hits += int(primary == expected)
            expected_secondary = set(case.get("expected_secondary") or [])
            predicted_secondary = set(secondary)
            secondary_tp += len(expected_secondary & predicted_secondary)
            secondary_fp += len(predicted_secondary - expected_secondary)
            secondary_fn += len(expected_secondary - predicted_secondary)
            if question.mapping_confidence is not None and question.mapping_confidence >= MATCHED_MIN_SCORE:
                high_conf_total += 1
                high_conf_correct += int(primary == expected)
                false_high_confidence += int(primary != expected)
            if primary != expected:
                if expected not in valid_unit_ids:
                    add_failure(case, question, predicted, "KNOWLEDGE_BASE_GAP")
                elif expected not in candidate_ids:
                    # The concept exists in the current teaching KB but was
                    # not retrieved into Top-K, including an empty candidate
                    # list.  It is therefore a retrieval miss, not a KB gap.
                    add_failure(case, question, predicted, "RETRIEVAL_MISS")
                else:
                    add_failure(case, question, predicted, "RERANKING_ERROR")
                if question.mapping_confidence is not None and question.mapping_confidence >= MATCHED_MIN_SCORE:
                    add_failure(case, question, predicted, "FALSE_HIGH_CONFIDENCE")
            if expected_secondary != predicted_secondary:
                add_failure(case, question, predicted, "RERANKING_ERROR")
        if case.get("expected_status"):
            expected_status = case["expected_status"]
            status_cases += 1
            forced_mapping += int(expected_status != "MATCHED" and question.mapping_status == "MATCHED")
            ambiguous_correct += int(expected_status == "AMBIGUOUS" and question.mapping_status == "AMBIGUOUS")
            unmatched_correct += int(expected_status == "UNMATCHED" and question.mapping_status == "UNMATCHED")
            if question.mapping_status != expected_status:
                add_failure(case, question, predicted, "FORCED_MAPPING" if question.mapping_status == "MATCHED" else "RERANKING_ERROR")

        expected_number = case.get("expected_question_number")
        if expected_number is not None:
            question_number_total += 1
            number_ok = str(expected_number) == str(question.question_number)
            if case.get("expected_subquestion_number") is not None:
                number_ok = number_ok and str(case["expected_subquestion_number"]) == str(question.subquestion_number)
            question_number_hits += int(number_ok)
            if not number_ok:
                add_failure(case, question, predicted, "QUESTION_NUMBER_ERROR")

        expected_material = case.get("expected_source_material_id")
        expected_location = case.get("expected_source_location")
        if expected_material is not None or expected_location is not None:
            provenance_total += 1
            provenance_ok = (expected_material is None or expected_material == question.source_material_id) and (expected_location is None or expected_location == question.source_location)
            provenance_hits += int(provenance_ok)
            if not provenance_ok:
                add_failure(case, question, predicted, "PROVENANCE_ERROR")
    def f1(precision: float | None, recall: float | None) -> float | None:
        return round(2 * precision * recall / (precision + recall), 4) if precision is not None and recall is not None and precision + recall else None
    secondary_precision = _safe_rate(secondary_tp, secondary_tp + secondary_fp)
    secondary_recall = _safe_rate(secondary_tp, secondary_tp + secondary_fn)
    all_current_questions = db.query(models.Question).filter(
        models.Question.course_id == dataset.get("course_id", ""),
        models.Question.source_type == "REAL_EXAM",
        models.Question.extraction_version == EXAM_INTELLIGENCE_VERSION,
    ).all()
    invalid_ids = 0
    over_primary = 0
    for question in all_current_questions:
        links = _active_question_links(db, question.id)
        invalid_ids += sum(1 for link in links if link.study_unit_id not in valid_unit_ids)
        over_primary += int(sum(1 for link in links if link.is_primary) > 1)

    annotated_materials = []
    segmentation_tp = segmentation_predicted = segmentation_expected = 0
    duplicate_count = duplicate_total = 0
    for annotation in _annotation_list(dataset):
        material_id = annotation.get("source_material_id")
        identities = _expected_identities(annotation)
        expected_count = annotation.get("expected_question_count")
        if not material_id or (not identities and not isinstance(expected_count, int)):
            continue
        annotated_materials.append(material_id)
        predicted_questions = [question for question in all_current_questions if question.source_material_id == material_id and question.segmentation_is_current is not False]
        unmatched = list(predicted_questions)
        matched = 0
        for expected_identity in identities:
            found = next((item for item in unmatched if _identity_matches(expected_identity, item)), None)
            if found is not None:
                unmatched.remove(found)
                matched += 1
        if not identities:
            expected_count = max(expected_count, 0)
            matched = min(len(predicted_questions), expected_count)
        segmentation_tp += matched
        segmentation_predicted += len(predicted_questions)
        segmentation_expected += expected_count if isinstance(expected_count, int) else len(identities)
        keys = [question.fingerprint or (question.question_number, question.subquestion_number, question.source_location, _normalise(question.content)) for question in predicted_questions]
        duplicate_count += len(keys) - len(set(keys))
        duplicate_total += len(keys)
        expected_total = expected_count if isinstance(expected_count, int) else len(identities)
        if matched != expected_total or matched != len(predicted_questions):
            add_failure(
                {"case_id": f"SEG-{material_id}", "question": "", "source_material_id": material_id,
                 "expected_primary": [], "expected_secondary": []},
                None,
                {"status": "SEGMENTATION", "candidates": [], "primary": None, "secondary": [], "confidence": None},
                "SEGMENTATION_ERROR",
            )
        predicted_numbers = {str(question.question_number) for question in predicted_questions}
        expected_numbers = {str(item.get("question_number")) for item in identities if item.get("question_number") is not None}
        for expected_identity in identities:
            if expected_identity.get("question_number") is None:
                continue
            question_number_total += 1
            number_ok = any(
                str(question.question_number) == str(expected_identity["question_number"])
                and (
                    expected_identity.get("subquestion_number") is None
                    or str(question.subquestion_number) == str(expected_identity["subquestion_number"])
                )
                for question in predicted_questions
            )
            question_number_hits += int(number_ok)
        if expected_numbers and predicted_numbers != expected_numbers:
            add_failure(
                {"case_id": f"SEG-NUM-{material_id}", "question": "", "source_material_id": material_id,
                 "expected_primary": [], "expected_secondary": []},
                None,
                {"status": "SEGMENTATION", "candidates": [], "primary": None, "secondary": [], "confidence": None},
                "QUESTION_NUMBER_ERROR",
            )
        for expected_identity in identities:
            if annotation.get("source_material_id") or expected_identity.get("source_location") or expected_identity.get("source_material_id"):
                provenance_total += 1
                found = next((item for item in predicted_questions if _identity_matches(expected_identity, item)), None)
                provenance_ok = found is not None and found.source_material_id == material_id and (not expected_identity.get("source_location") or found.source_location == expected_identity["source_location"])
                provenance_hits += int(provenance_ok)
                if not provenance_ok:
                    add_failure(
                        {"case_id": f"PROV-{material_id}-{expected_identity.get('question_number', 'unknown')}", "question": "", "source_material_id": material_id,
                         "expected_primary": [], "expected_secondary": []},
                        found,
                        {"status": "SEGMENTATION", "candidates": [], "primary": None, "secondary": [], "confidence": None},
                        "PROVENANCE_ERROR",
                    )

    segmentation_precision = _safe_rate(segmentation_tp, segmentation_predicted) if annotated_materials else None
    segmentation_recall = _safe_rate(segmentation_tp, segmentation_expected) if annotated_materials else None
    segmentation_f1 = f1(segmentation_precision, segmentation_recall) if annotated_materials else None
    duplicate_rate = _safe_rate(duplicate_count, duplicate_total) if annotated_materials else None
    question_number_annotations = _question_number_annotations(dataset)
    for annotation in question_number_annotations:
        question = db.get(models.Question, annotation.get("question_id"))
        if question is None or annotation.get("expected_question_number") is None:
            continue
        question_number_total += 1
        number_ok = str(annotation["expected_question_number"]) == str(question.question_number)
        question_number_hits += int(number_ok)
        if not number_ok:
            add_failure(annotation, question, {"status": question.mapping_status, "primary": None, "secondary": [], "confidence": question.mapping_confidence, "candidates": []}, "QUESTION_NUMBER_ERROR")

    source_provenance_coverage = _safe_rate(provenance_hits, provenance_total) if provenance_total else None
    mapping_all = _mapping_metrics_for_cases(db, reviewed, units)
    mapping_gated = _mapping_metrics_for_cases(db, reviewed, units, eligible_only=True)
    eligible_questions = sum(int(question.is_mapping_eligible is True) for question in all_current_questions)
    ineligible_questions = len(all_current_questions) - eligible_questions
    quality_annotations = dataset.get("question_quality_annotations") or dataset.get("quality_annotations") or []
    if isinstance(quality_annotations, dict):
        quality_annotations = list(quality_annotations.values())
    quality_annotations = [item for item in quality_annotations if isinstance(item, dict)]
    bad_quality = [item for item in quality_annotations if item.get("expected_mapping_eligible") is False]
    clean_quality = [item for item in quality_annotations if item.get("expected_mapping_eligible") is True]
    quality_rejection_recall = None
    clean_acceptance_rate = None
    if bad_quality or clean_quality:
        quality_lookup = {item.get("question_id"): item for item in quality_annotations}
        rejected_bad = 0
        accepted_clean = 0
        for question in all_current_questions:
            annotation = quality_lookup.get(question.id)
            if not annotation:
                continue
            if annotation.get("expected_mapping_eligible") is False:
                rejected_bad += int(question.is_mapping_eligible is not True)
            elif annotation.get("expected_mapping_eligible") is True:
                accepted_clean += int(question.is_mapping_eligible is True)
        quality_rejection_recall = _safe_rate(rejected_bad, len(bad_quality)) if bad_quality else None
        clean_acceptance_rate = _safe_rate(accepted_clean, len(clean_quality)) if clean_quality else None
    segmentation_status_counts = Counter(question.segmentation_status or "UNKNOWN" for question in all_current_questions)
    top_failure_cases.sort(key=lambda item: (item.get("confidence") is not None, item.get("confidence") or 0), reverse=True)
    return {
        "ground_truth_cases": len(cases), "reviewed_cases": len(reviewed),
        "stale_cases": sum(1 for case in cases if case.get("stale")),
        "metrics": {
            "segmentation_precision": segmentation_precision, "segmentation_recall": segmentation_recall, "segmentation_f1": segmentation_f1,
            "question_number_accuracy": _safe_rate(question_number_hits, question_number_total) if question_number_total else None,
            "source_provenance_coverage": source_provenance_coverage,
            "duplicate_rate": duplicate_rate,
            "top_1_recall": _safe_rate(top_hits[1], len(reviewed)) if reviewed else None,
            "top_3_recall": _safe_rate(top_hits[3], len(reviewed)) if reviewed else None,
            "top_5_recall": _safe_rate(top_hits[5], len(reviewed)) if reviewed else None,
            "primary_top_1_accuracy": _safe_rate(primary_hits, len(reviewed)) if reviewed else None,
            "secondary_precision": secondary_precision if reviewed else None,
            "secondary_recall": secondary_recall if reviewed else None,
            "secondary_f1": f1(secondary_precision, secondary_recall) if reviewed else None,
            "high_confidence_accuracy": _safe_rate(high_conf_correct, high_conf_total),
            "false_high_confidence_rate": _safe_rate(false_high_confidence, high_conf_total),
            "forced_mapping_rate": _safe_rate(forced_mapping, status_cases) if status_cases else None,
            "ambiguous_correctness": _safe_rate(ambiguous_correct, status_cases) if status_cases else None,
            "unmatched_correctness": _safe_rate(unmatched_correct, status_cases) if status_cases else None,
            "invalid_study_unit_id_count": invalid_ids, "questions_with_gt_1_primary": over_primary,
        },
        "metrics_all_cases": mapping_all,
        "metrics_quality_gated": mapping_gated,
        "quality_gate": {
            "eligible_questions": eligible_questions,
            "ineligible_questions": ineligible_questions,
            "bad_question_rejection_recall": quality_rejection_recall,
            "clean_question_acceptance_rate": clean_acceptance_rate,
            "quality_annotation_status": "AVAILABLE" if quality_annotations else "UNKNOWN",
            "segmentation_status_counts": dict(segmentation_status_counts),
        },
        "failure_breakdown": dict(failure_breakdown), "top_failure_cases": top_failure_cases[:50],
        "note": "No cases are marked REVIEWED and no segmentation annotations are supplied; metrics requiring human ground truth are intentionally reported as null." if not reviewed and not annotated_materials else "Metrics computed from supplied human annotations.",
    }


def write_evaluation_report(report_dir: str | Path, dataset: dict, processing: dict, evaluation: dict) -> tuple[Path, Path]:
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    full = {
        "summary": evaluation, "processing": processing,
        "engineering": {
            "pdf_reparse_count": processing.get("parser_calls", 0),
            "ocr_reparse_count": processing.get("ocr_calls", 0),
            "extracted_text_mutation_count": processing.get("extracted_text_mutation_count", 0),
        },
        "quality_gate": evaluation.get("quality_gate", {}),
        "mapping_metrics_all_cases": evaluation.get("metrics_all_cases", {}),
        "mapping_metrics_quality_gated": evaluation.get("metrics_quality_gated", {}),
        "targets": {"segmentation_precision": 0.95, "segmentation_recall": 0.95, "top5_recall": 0.95, "primary_top1_accuracy": 0.85, "forced_mapping_rate": 0.05},
    }
    json_path = report_path / "latest_report.json"
    md_path = report_path / "latest_report.md"
    json_path.write_text(json.dumps(full, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    m = evaluation["metrics"]
    md = "\n".join([
        "# Exam Intelligence Evaluation Report", "", "## SUMMARY", "",
        f"Ground Truth cases: {evaluation['ground_truth_cases']}", f"Reviewed cases: {evaluation['reviewed_cases']}", f"Stale cases: {evaluation.get('stale_cases', 0)}", "",
        f"Segmentation Precision: {m['segmentation_precision']}", f"Segmentation Recall: {m['segmentation_recall']}", f"Segmentation F1: {m['segmentation_f1']}",
        f"Top-1 Recall: {m['top_1_recall']}", f"Top-3 Recall: {m['top_3_recall']}", f"Top-5 Recall: {m['top_5_recall']}",
        f"Primary Top-1 Accuracy: {m['primary_top_1_accuracy']}", f"Secondary Precision: {m['secondary_precision']}", f"Secondary Recall: {m['secondary_recall']}", f"Secondary F1: {m['secondary_f1']}",
        f"High-confidence Accuracy: {m['high_confidence_accuracy']}", f"False High-confidence Rate: {m['false_high_confidence_rate']}", f"Forced Mapping Rate: {m['forced_mapping_rate']}",
        f"AMBIGUOUS correctness: {m['ambiguous_correctness']}", f"UNMATCHED correctness: {m['unmatched_correctness']}", f"Question Number Accuracy: {m['question_number_accuracy']}", f"Source Provenance Coverage: {m['source_provenance_coverage']}",
        f"Invalid Mapping Count: {m['invalid_study_unit_id_count']}", f">1 Primary Count: {m['questions_with_gt_1_primary']}", "",
        "## LAYER B — QUESTION QUALITY GATE", "",
        f"Eligible questions: {evaluation.get('quality_gate', {}).get('eligible_questions')}",
        f"Ineligible questions: {evaluation.get('quality_gate', {}).get('ineligible_questions')}",
        f"Bad-question rejection recall: {evaluation.get('quality_gate', {}).get('bad_question_rejection_recall')}",
        f"Clean-question acceptance rate: {evaluation.get('quality_gate', {}).get('clean_question_acceptance_rate')}",
        f"Quality annotations: {evaluation.get('quality_gate', {}).get('quality_annotation_status')}",
        f"Segmentation statuses: {evaluation.get('quality_gate', {}).get('segmentation_status_counts')}", "",
        "## LAYER C — MAPPING BY POPULATION", "",
        "### ALL CASES", "",
        *(f"{key}: {value}" for key, value in evaluation.get("metrics_all_cases", {}).items()), "",
        "### QUALITY-GATED CASES ONLY", "",
        *(f"{key}: {value}" for key, value in evaluation.get("metrics_quality_gated", {}).items()), "",
        f"PDF Reparse: {full['engineering']['pdf_reparse_count']}", f"OCR Reparse: {full['engineering']['ocr_reparse_count']}", f"Extracted Text Mutation: {full['engineering']['extracted_text_mutation_count']}",
        "", "## FAILURE BREAKDOWN", "",
        *(f"{name}: {count}" for name, count in sorted(evaluation.get("failure_breakdown", {}).items())),
        "(none)" if not evaluation.get("failure_breakdown") else "",
        "", "## TOP FAILURE CASES", "",
        *(
            f"- {item['case_id']} | {item['failure_type']} | material={item.get('source_material_id')} | location={item.get('source_location')} | confidence={item.get('confidence')}\n  question: {item.get('question', '')[:240]}"
            for item in evaluation.get("top_failure_cases", [])
        ),
        "(none)" if not evaluation.get("top_failure_cases") else "", "", evaluation["note"],
    ]) + "\n"
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
