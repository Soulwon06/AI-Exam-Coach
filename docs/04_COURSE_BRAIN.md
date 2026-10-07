# AI-Exam-Coach — Course Brain

## Pipeline
Teaching Material (`TEXTBOOK` / `TEACHER_PPT` / `CLASS_NOTES`) → Parse → Course
Knowledge Base → canonical Study Units.

`REAL_EXAM` follows a separate evidence path:

`Material.extracted_text` → Question Segmentation → Question Provenance →
Candidate Retrieval (existing StudyUnits only) → Validation → Exam Evidence.

REAL_EXAM never creates a StudyUnit. Mapping may be `MATCHED`, `AMBIGUOUS`, or
`UNMATCHED`; low confidence is preserved as abstention rather than forced into a
knowledge point.

## Evidence types
`REAL_EXAM`, `EXAM_SCOPE`, `TEACHER_PPT`, `TEXTBOOK`, `BILIBILI`, `CLASS_NOTES`, `HOMEWORK`, `LAB`, `OTHER`.

## Priority
1. Real exam evidence
2. Exam scope / teacher emphasis
3. Supporting course evidence

Exact numerical weights are configuration, not UI copy.

## Study Unit
A coherent, learnable unit that is small enough for one session but not arbitrarily tiny. It must support explanation and practice and link to evidence and questions.

### Extraction quality gate
A Study Unit is persisted only when it has a short, inspectable source excerpt
from the uploaded material. Paragraphs, answer keys, page headers, file names and
question stems are never promoted directly to knowledge points. For offline
extraction, explicit headings are preferred; an exam-derived point requires the
same target to recur in at least two questions. If the system cannot identify a
grounded point, it reports insufficient evidence instead of guessing.

Each Study Unit links only to the evidence excerpt that supports that unit. A
material-wide summary must not be attached to every unit. This preserves the
meaning of exam frequency and makes the learning explanation auditable.

## Question mapping
A question may map to multiple Study Units. Support `is_primary` and `relevance_score`.
Only explicit targets or a strong lexical match may create that mapping; an
unmatched question remains available as source data but is not assigned to an
arbitrary first knowledge point.

Exam Intelligence v1 stores the source material, year, question/subquestion
number, source location, raw excerpt, extraction version, deterministic
fingerprint, mapping confidence/status, and an `ExamEvidence` row for each
validated primary/secondary link.

## Splitting
MVP supports basic question splitting where feasible. Every split question retains `parent_question_id` and a “查看原题” entry. Advanced decomposition is V1.

## Incremental updates
Adding a new source reuses study units with the same title instead of creating
duplicates, then re-scores importance. Deleting a source removes its Evidence,
any StudyUnits/Questions that now have no other supporting evidence, and the
mapping between them, preserving student mastery and re-scoring importance.
The course is never fully re-analyzed on an incremental change.

## Failures
A failed optional source must not block a usable course.

## Bilibili
Attempt supported public transcript/subtitle/metadata extraction. If unavailable, mark that evidence failed and continue with other sources.

## Image-heavy questions
If reliable image understanding is unavailable, preserve the original question rather than fabricating a visually dependent question.

## No invented practice
If a knowledge point has no reliably extracted, mapped and gradeable question,
the practice endpoint returns `QUESTION_NOT_AVAILABLE`. The UI must explain that
the current material lacks a reliable practice item; it must not generate a
placeholder question and treat it as course evidence.
