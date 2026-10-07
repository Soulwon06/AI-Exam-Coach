"""Providers for the Course Brain extraction contract.

The offline provider deliberately favours *traceable* concepts over recall.
Every returned study unit carries the exact source line that supports it and every
question carries one or more candidate targets.  A plausible OCR line is not a
knowledge point by itself.
"""
from abc import ABC, abstractmethod
from collections import Counter
from difflib import SequenceMatcher
import json
import os
import re
import unicodedata


_WEIRD_RE = re.compile(r"[*|~^=`{}\\\\]")
_QSTART = re.compile(r"^(?:\d+|[一二三四五六七八九十]+|[（(]\d+[)）])\s*[.、．.)、]?\s*(.+)$")
_OPTION = re.compile(r"^([A-D])\s*[.、．.)、]\s*(.+)$")
_OPTION_LIKE = re.compile(r"^(?:[•·▪●○]|[（(]?[A-Ha-h][)）.、:])\s*")
_PURE_ANSWER_KEY = re.compile(r"^(?:[A-Da-d])(?:\s+[A-Da-d])+$")
_ANSWER_LINE = re.compile(
    r"^(?:答案|正确答案|参考答案|标准答案|正确选项|判断题答案|选择题答案|答案提示|答案说明)"
    r"\s*[:：为是]?\s*(?:[A-D]{1,4}|正确|错误|对|错|√|×|T(?:\s*[A-F])*|F)?\s*$", re.IGNORECASE
)
_SECTION_LINE = re.compile(r"^[一二三四五六七八九十]+[、.]?\s*(?:大题|单选题|多选题|选择题|判断题|简答题|论述题|计算题|填空题|应用题|综合题)\s*(?:（.*）)?$")
_ANSWER_KEY = re.compile(r"(?:答案|正确答案|参考答案|标准答案|正确选项)\s*[:：为是]?\s*([A-D]{1,4}|正确|错误|对|错|√|×|T|F|TRUE|FALSE)", re.IGNORECASE)
_TF_OPTION = re.compile(r"^([A-D])\s*[.、．.)、]\s*(正确|错误|对|错|√|×|T|F|TRUE|FALSE)\s*$", re.IGNORECASE)
_PAGE_MARKER = re.compile(r"^-+\s*(?:page|image)\s+[^-]+\s*-+$", re.IGNORECASE)
_DATE_OR_TIME = re.compile(r"(?:20\d{2}\s*[年/.-]\s*\d{1,2}\s*[月/.-]\s*\d{1,2}|\d{1,2}\s*[月/]\s*\d{1,2}|\b\d{1,2}:\d{2}\b)")
_FILE_NAME = re.compile(r"(?:[A-Za-z]:[\\/]|/mnt/|\b[^\s]+\.(?:pdf|docx?|pptx?|txt|md)\b)", re.IGNORECASE)
_METADATA_EXACT = {
    "考试时间", "考试日期", "课程名称", "课程名", "授课院 (系)", "授课院系",
    "版权所有", "收集", "制作", "属性", "试卷", "提示", "hint", "material",
}
_METADATA_PREFIX = re.compile(
    r"^(?:考试时间|考试日期|考试课程|课程名称|课程名|授课院|版权所有|copyright|"
    r"收集|制作(?:团队|人|者|于)?|来源|出处|整理|扫码|公众号|仅供参考|material|external link)"
    r"(?:\s*[:：]|\s|$)",
    re.IGNORECASE,
)
_GENERIC_TOPIC_TITLES = {
    "数据库", "数据库系统", "database", "database system", "database systems",
    "计算机网络", "computer network", "computer networks", "操作系统", "数据结构",
}
_GENERIC_WORDS = {"属性", "课程", "试卷", "问题", "信息", "数据", "表", "模式", "hint"}
_INSTRUCTION_FRAGMENT = re.compile(
    r"(?:对于每个|针对.+题|给出(?:以下|对应|满足)|查询(?:以下|如下)|请回答|本题|"
    r"假设.+(?:具有|上的|如下)|设计一个|找到符合|结果应该|备份数据库|以下信息|"
    r"(?:模式|表|数据库)结构如下|结构如下$|提示$)",
)
_ENGLISH_FRAGMENT = re.compile(
    r"^(?:list as|needed is|query as follows|are defined as follows|are deﬁned as follows|"
    r"query has the form|the query|as follows|instead of|which can be written as|"
    r"is equivalent to|following example|following syntax|following queries|"
    r"the following|which is|of the following|a record as follows|site contains|"
    r"of major disadvantages|not removed|columns|name|hint|average|minimum|maximum|count)$",
    re.IGNORECASE,
)
_ENGLISH_TECHNICAL = re.compile(
    r"\b(?:sql|dbms|database|relational|relation|algebra|normalization|normal form|"
    r"functional dependency|candidate key|primary key|foreign key|transaction|"
    r"concurrency|isolation|deadlock|index|b-tree|hash index|view|join|subquery|"
    r"aggregate function|group by|select|insert|update|delete|stored procedure|"
    r"trigger|cursor|schema|entity|er model|constraint|acid|tcp|udp|http|dns|arp|"
    r"osi|ip address|routing|algorithm|protocol)\b",
    re.IGNORECASE,
)
_TWO_CHAR_CONCEPTS = {"事务", "视图", "索引", "范式", "死锁", "查询", "连接", "函数", "协议"}
_CONCEPT_MARKER = re.compile(
    r"(?:协议|模型|模式|范式|约束|事务|视图|索引|锁|算法|结构|原理|机制|方法|语言|"
    r"查询|关系代数|候选码|函数依赖|完整性|规范化|连接|子查询|触发器|游标|"
    r"存储过程|并发|隔离|死锁|键|码|聚合|选择|投影|联接|数据库|SQL|TCP|UDP|IP|OSI|HTTP|DNS|ARP)",
    re.IGNORECASE,
)
_ENGLISH_LEADING_FRAGMENT = re.compile(
    r"^(?:the|a|an|this|here|following|for each|each|which|that|these|those|"
    r"current|instead|as|of|and|or|may|can|are|is|needed|list|query)\b",
    re.IGNORECASE,
)
_ENGLISH_TRAILING_FRAGMENT = re.compile(
    r"\b(?:as|is|are|can|may|which|following|below|underlined|contains|written)$",
    re.IGNORECASE,
)
_CODE_FRAGMENT = re.compile(
    r"\b(?:exec\s+sql|sql\s+iterator|select\s+.+\s+from|insert\s+into|update\s+.+\s+set|delete\s+from)\b",
    re.IGNORECASE,
)


def _normalise_line(line: str) -> str:
    """Make PDF/OCR line breaks comparable without inventing text."""
    # NFKC fixes OCR ligatures such as ``deﬁned`` but also turns Chinese
    # punctuation into ASCII. Preserve punctuation that is part of question
    # evidence so cleaning does not rewrite the material shown to learners.
    preserve = {
        "？": "\\ue000", "：": "\\ue001", "，": "\\ue002", "。": "\\ue003",
        "；": "\\ue004", "（": "\\ue005", "）": "\\ue006", "【": "\\ue007",
        "】": "\\ue008", "《": "\\ue009", "》": "\\ue00a", "、": "\\ue00b",
    }
    value = (line or "").translate(str.maketrans(preserve))
    value = unicodedata.normalize("NFKC", value)
    for original, placeholder in preserve.items():
        value = value.replace(placeholder, original)
    value = value.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def _metadata_reason(line: str) -> str | None:
    value = _normalise_line(line)
    lower = value.casefold()
    if not value:
        return "empty-line"
    if _PAGE_MARKER.match(value):
        return "page-marker"
    if lower in _METADATA_EXACT or lower in _GENERIC_TOPIC_TITLES:
        return "metadata-or-generic-topic"
    if _FILE_NAME.search(value) or re.match(r"^(?:material|external link)\s*[:：]", value, re.IGNORECASE):
        return "file-or-source-label"
    if _METADATA_PREFIX.match(value):
        return "exam-or-copyright-metadata"
    if _DATE_OR_TIME.search(value) and re.search(r"(?:考试|课程|日期|时间|学期|班级|学号|姓名|总分|分数)", value):
        return "exam-date-or-time-metadata"
    return None


def _looks_like_repeated_header(value: str) -> bool:
    if len(value) > 100 or _QSTART.match(value) or _OPTION.match(value) or "?" in value or "？" in value:
        return False
    return True


def _candidate_quality_reason(title: str) -> str | None:
    value = _normalise_line(title).strip("。．.")
    compact = re.sub(r"\s+", "", value)
    lower = value.casefold()
    if not value:
        return "empty-candidate"
    if lower in _METADATA_EXACT or lower in _GENERIC_TOPIC_TITLES:
        return "metadata-or-overbroad-topic"
    if lower in _GENERIC_WORDS:
        return "generic-word"
    if _INSTRUCTION_FRAGMENT.search(value):
        return "question-or-instruction-fragment"
    if _OPTION_LIKE.match(value):
        return "option-or-list-item"
    if _CODE_FRAGMENT.search(value):
        return "code-or-example-fragment"
    if (
        _ENGLISH_FRAGMENT.match(value)
        or _ENGLISH_LEADING_FRAGMENT.match(value)
        or _ENGLISH_TRAILING_FRAGMENT.search(value)
        or re.search(r"\bas follows$|\bare (?:deﬁned|defined) as follows$", value, re.IGNORECASE)
    ):
        return "english-sentence-fragment"
    if re.fullmatch(r"[A-Za-z\s]+", value):
        if not _ENGLISH_TECHNICAL.search(value):
            return "non-technical-english-phrase"
        if len(value.split()) < 2 and value.casefold() not in {"sql", "dbms", "tcp", "udp", "osi", "http", "dns", "arp"}:
            return "short-english-fragment"
    if len(compact) < 2:
        return "too-short"
    if len(compact) == 2 and compact not in _TWO_CHAR_CONCEPTS and not re.search(r"[A-Za-z0-9]", compact):
        return "too-short-or-generic"
    if len(compact) > 42:
        return "too-long-for-knowledge-point"
    if re.search(r"^(?:[A-Za-z]|[\u4e00-\u9fff])\s*的(?:候选码|模型|锁)", value, re.IGNORECASE):
        return "ocr-fragment"
    if re.search(r"^[A-Za-z][\u4e00-\u9fff]{1,3}(?:模型|锁)$", value, re.IGNORECASE):
        return "ocr-fragment"
    if re.search(r"^[A-Za-z]+\s*(?:（[^）]{1,12}）)?模式$", value) and not re.match(r"^(?:E-?R|ER|关系)\b", value, re.IGNORECASE):
        return "example-schema-not-concept"
    if re.search(r"模型$", value) and not re.match(
        r"^(?:关系|数据|概念|逻辑|物理|层次|网状|面向对象|E-?R|ER).{0,8}模型$", value, re.IGNORECASE
    ):
        return "unrecognized-model-or-ocr-fragment"
    if not _CONCEPT_MARKER.search(value) and not re.search(r"(?:[A-Z]{2,}|\d+[A-Za-z]|[A-Za-z]+\d)", value):
        return "no-domain-semantic-signal"
    return None


def _near_duplicate(title: str, accepted: list[str]) -> bool:
    key = _dedupe_key(title)
    for existing in accepted:
        other = _dedupe_key(existing)
        if key == other:
            return True
        if min(len(key), len(other)) >= 5 and SequenceMatcher(None, key, other).ratio() >= 0.9:
            return True
    return False


def _is_readable_line(line: str) -> bool:
    if not line or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", line) or _WEIRD_RE.search(line):
        return False
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in line)
    if cjk:
        return cjk / len(line) >= 0.25
    letters = sum(char.isascii() and char.isalpha() for char in line)
    return len(line.split()) >= 2 and (letters + line.count(" ")) / len(line) >= 0.85


def _clean_title(value: str) -> str:
    value = re.sub(r"^(?:第?[一二三四五六七八九十\d]+[章节篇]|[一二三四五六七八九十\d]+[、.．])\s*", "", value.strip())
    value = re.sub(r"^[#*\-·\s]+|[#*\-·\s]+$", "", value)
    return re.sub(r"\s+", " ", value)[:80]


def _title_from_line(line: str) -> str:
    """Return an explicitly delimited concept title, or an empty string.

    This deliberately refuses ordinary prose.  A short sentence can look like a
    sensible label to a human, but treating it as one is what polluted the old
    graph with explanations and question stems.
    """
    value = _clean_title(line)
    if not (2 <= len(value) <= 42) or not _is_readable_line(value):
        return ""
    if _QSTART.match(line) or re.search(r"[?？]\s*$|[（(]\s*[）)]\s*$", value):
        return ""
    if _OPTION.match(value) or _PURE_ANSWER_KEY.match(value) or _ANSWER_LINE.match(value) or _SECTION_LINE.match(value):
        return ""
    if line.lstrip().startswith("#") or re.match(r"^(?:第?[一二三四五六七八九十\d]+[章节篇]|[一二三四五六七八九十\d]+[、.．])", line):
        return value
    if "：" in value or ":" in value:
        candidate = _clean_title(re.split(r"[：:]", value, maxsplit=1)[0])
        return candidate if 2 <= len(candidate) <= 24 else ""
    compact = value.rstrip("。.")
    if len(compact) <= 20 and re.search(r"(?:协议|模型|范式|约束|事务|视图|索引|锁|算法|结构|原理|机制|方法|语言|过程|区别)$", compact):
        return compact
    return ""


def _question_targets(question: str) -> list[str]:
    """Extract conservative noun phrases from a question as mapping targets."""
    text = re.sub(r"^(?:\d+|[一二三四五六七八九十]+)[.、．.)\s]*", "", question).strip()
    patterns = (
        r"(?:关于|有关)([\u4e00-\u9fffA-Za-z0-9+/.-]{2,24})(?:的|，|,|。|是|有|不|正确|错误)",
        r"([\u4e00-\u9fffA-Za-z0-9+/.-]{2,24})(?:协议|模型|范式|约束|事务|视图|索引|锁|算法|结构|原理|机制|方法|语言|关系)(?:的|是|有|包括|中|主要|属于|可以|应|不)",
        r"([A-Za-z][A-Za-z0-9+/.-]{1,20})(?:协议|模型|范式|约束|事务|视图|索引|锁|算法|结构|原理|机制|方法|语言)",
    )
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = _clean_title(match.group(1))
            if 2 <= len(candidate) <= 32 and candidate not in found:
                found.append(candidate)
    return found[:3]


class AIProvider(ABC):
    @abstractmethod
    def analyze_material(self, text: str, material_type: str) -> dict:
        """Return units with evidence snippets and gradeable questions."""
        raise NotImplementedError


class HeuristicProvider(AIProvider):
    """Offline, evidence-first fallback.

    Explicit headings become concepts. Exam questions supply mapping targets, but
    do not become concepts unless a target repeats; this avoids turning stems into
    a polluted knowledge graph.
    """

    def analyze_material(self, text: str, material_type: str) -> dict:
        raw_lines = [line for line in text.splitlines() if line.strip()]
        lines, trace = self._prepare_lines(raw_lines, text)
        questions = self._extract_questions(lines)
        units = self._extract_units(lines, questions, trace)
        trace["final_knowledge_points"] = [unit["title"] for unit in units]
        if os.getenv("AEC_EXTRACTION_TRACE", "").casefold() in {"1", "true", "yes"}:
            print("[AEC_EXTRACTION_TRACE]" + json.dumps(trace, ensure_ascii=False))
        return {"study_units": units, "questions": questions, "evidence": [], "trace": trace}

    @staticmethod
    def _prepare_lines(raw_lines: list[str], raw_text: str) -> tuple[list[str], dict]:
        """Normalize extracted lines and remove only high-confidence noise.

        This is deliberately before question/unit extraction: PDF text order and
        OCR line boundaries are input quality problems, not prompt problems.
        """
        normalised = [_normalise_line(line) for line in raw_lines]
        counts = Counter(_dedupe_key(line) for line in normalised if line)
        cleaned: list[str] = []
        filtered: list[dict] = []
        trace = {
            "raw_text_sample": (raw_text or "")[:4000],
            "cleaned_text_sample": "",
            "raw_line_count": len(raw_lines),
            "cleaned_line_count": 0,
            "cleaning": [],
            "generated_candidates": [],
            "filtered_candidates": filtered,
            "final_knowledge_points": [],
        }
        has_page_markers = any(_PAGE_MARKER.match(item) for item in normalised)
        for raw, value in zip(raw_lines, normalised):
            if not value:
                trace["cleaning"].append({"raw": raw[:240], "cleaned": "", "reason": "empty-line"})
                continue
            reason = _metadata_reason(value)
            if (
                reason is None
                and counts[_dedupe_key(value)] >= 2
                and (has_page_markers or counts[_dedupe_key(value)] >= 3)
                and _looks_like_repeated_header(value)
            ):
                reason = "repeated-header-or-footer"
            if reason:
                item = {"raw": raw[:240], "cleaned": value[:240], "reason": reason}
                trace["cleaning"].append(item)
                if reason not in {"empty-line", "page-marker", "repeated-header-or-footer"}:
                    filtered.append({"candidate": value[:120], "evidence": value[:240], "reason": reason, "stage": "preprocess"})
                continue
            cleaned.append(value)
            if raw.strip() != value:
                trace["cleaning"].append({"raw": raw[:240], "cleaned": value[:240], "reason": "normalized"})
        trace["cleaned_line_count"] = len(cleaned)
        trace["cleaned_text_sample"] = "\n".join(cleaned)[:4000]
        return cleaned, trace

    def _extract_units(self, lines: list[str], questions: list[dict], trace: dict | None = None) -> list[dict]:
        units: list[dict] = []
        accepted_titles: list[str] = []
        for line in lines:
            title = _title_from_line(line)
            if title:
                if trace is not None:
                    trace["generated_candidates"].append({"title": title, "evidence": line[:300], "source": "STRUCTURAL"})
                reason = _candidate_quality_reason(title)
                if reason:
                    if trace is not None:
                        trace["filtered_candidates"].append({"candidate": title, "evidence": line[:300], "reason": reason, "stage": "candidate-quality"})
                    continue
                if _near_duplicate(title, accepted_titles):
                    if trace is not None:
                        trace["filtered_candidates"].append({"candidate": title, "evidence": line[:300], "reason": "duplicate-or-near-duplicate", "stage": "deduplication"})
                    continue
                units.append({"title": title, "evidence": line, "confidence": "STRUCTURAL"})
                accepted_titles.append(title)

        targets: dict[str, list[str]] = {}
        for question in questions:
            for target in question.get("knowledge_titles", []):
                targets.setdefault(target, []).append(question["content"])
        for target, source_lines in targets.items():
            if len(source_lines) < 2:
                continue
            if trace is not None:
                trace["generated_candidates"].append({"title": target, "evidence": "\n".join(source_lines[:3])[:300], "source": "REPEATED_EXAM_TARGET"})
            reason = _candidate_quality_reason(target)
            if reason:
                if trace is not None:
                    trace["filtered_candidates"].append({"candidate": target, "evidence": "\n".join(source_lines[:3])[:300], "reason": reason, "stage": "candidate-quality"})
                continue
            if _near_duplicate(target, accepted_titles):
                if trace is not None:
                    trace["filtered_candidates"].append({"candidate": target, "evidence": "\n".join(source_lines[:3])[:300], "reason": "duplicate-or-near-duplicate", "stage": "deduplication"})
                continue
            units.append({"title": target, "evidence": "\n".join(source_lines[:3]), "confidence": "REPEATED_EXAM_TARGET"})
            accepted_titles.append(target)
        return units[:80]

    def _extract_questions(self, lines: list[str]) -> list[dict]:
        questions: list[dict] = []
        index = 0
        while index < len(lines):
            if _QSTART.match(lines[index]) is None:
                index += 1
                continue
            block = [lines[index]]
            cursor = index + 1
            while cursor < len(lines) and _QSTART.match(lines[cursor]) is None:
                block.append(lines[cursor])
                cursor += 1
            parsed = self._parse_question_block(block)
            if parsed is not None:
                questions.append(parsed)
            index = cursor
        return questions[:80]

    def _parse_question_block(self, block: list[str]) -> dict | None:
        content_parts = [block[0]]
        options: list[str] = []
        answer = ""
        tf_options = False
        for line in block[1:]:
            tf_match = _TF_OPTION.match(line)
            if tf_match:
                options.append(f"{tf_match.group(1)}. {tf_match.group(2)}")
                tf_options = True
                continue
            option_match = _OPTION.match(line)
            if option_match:
                options.append(f"{option_match.group(1)}. {option_match.group(2)}")
                continue
            answer_match = _ANSWER_KEY.search(line)
            if answer_match:
                answer = self._normalize_answer(answer_match.group(1))
                continue
            content_parts.append(line)
        content = " ".join(content_parts).strip()
        if len(content) < 6 or not answer:
            return None
        is_tf = tf_options or "判断" in content
        if is_tf:
            answer = self._normalise_tf(answer)
        if not answer:
            return None
        return {"content": content[:1200], "type": "TRUE_FALSE" if is_tf else ("MULTIPLE_CHOICE" if len(answer) > 1 else "SINGLE_CHOICE"), "answer": answer, "options": options or None, "knowledge_titles": _question_targets(content), "evidence": "\n".join(block)[:3000]}

    @staticmethod
    def _normalize_answer(value: str) -> str:
        return re.sub(r"[．。、\s]+", "", (value or "").strip()).upper()

    @staticmethod
    def _normalise_tf(value: str) -> str:
        if value in ("T", "TRUE", "对", "正确", "√", "YES"):
            return "T"
        if value in ("F", "FALSE", "错", "错误", "×", "NO"):
            return "F"
        return ""
