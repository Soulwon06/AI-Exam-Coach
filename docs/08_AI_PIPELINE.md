# AI-Exam-Coach — AI Pipeline

Frontend never calls an AI provider directly.

Architecture: Frontend → FastAPI → Application Service → AI Service → AI Provider.

## Pipeline
1. Parse files/links and persist `Material.extracted_text`.
2. Build the Course Knowledge Base from teaching materials only.
3. Extract Knowledge Domains and canonical Study Units.
4. For `REAL_EXAM`, segment questions from persisted extracted text and attach provenance.
5. Run the Question Intelligence Quality Gate: validate boundaries, source
   integrity, and recoverable parent/shared context. Preserve the original
   question and store `effective_question_context` separately.
6. Retrieve and deterministically validate candidates from existing StudyUnits
   only when `is_mapping_eligible` is true.
7. Persist `MATCHED` / `AMBIGUOUS` / `UNMATCHED` mapping and Exam Evidence only
   for eligible questions. Rejected derived rows are retained but marked inactive.
8. Generate grounded explanations.
9. Optionally generate validated simulation questions (P2).

Exam Intelligence v1 does not call the material parser when cached text is
available. Its baseline sends no full PDF or textbook to an LLM; any future
LLM-assisted reranker must receive only a question and its bounded Top-K
candidates and must pass schema/StudyUnit-ID validation.

The quality gate is deterministic and does not modify `Material.extracted_text`.
Merged or incomplete boundaries, corrupted source text, missing image/symbol
content, and unresolved context are ineligible for automatic mapping.

## Grounding
Prefer course evidence over generic knowledge. Do not invent teacher-specific claims when evidence is insufficient.

## Async jobs
Parsing, extraction, mapping, Course Brain building, and large AI operations run asynchronously.

Statuses: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

## Validation
Validate AI JSON/schema, referenced IDs, question structure, and reject malformed outputs.

## Simulation
Never present generated simulation questions as real exam questions. Label them clearly.
