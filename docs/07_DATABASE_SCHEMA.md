# AI-Exam-Coach — Database Schema

## Tables
- `users`: id, created_at
- `courses`: id, user_id, name, school, teacher, exam_date, status, timestamps
- `user_preferences`: id, user_id, course_id, learning_mode, simulation_mode, timestamps
- `materials`: id, course_id, type, source, file_path/external_url, worker status, parsing_status, parser_method, parser_version, extracted_text, extracted_char_count, extraction_quality, extraction_error, file_hash, progress, error_code, timestamps
- `evidences`: id, material_id, evidence_type, content_reference, metadata
- `knowledge_domains`: id, course_id, parent_id, title, order_index
- `study_units`: id, course_id, domain_id, title/canonical_name, source_material_id, source_type, source_excerpt, source_location, importance_score, difficulty_score, mastery_status, coverage_status, progress, estimated_minutes, timestamps
- `study_unit_evidences`: study_unit_id, evidence_id, relevance_score
- `questions`: id, course_id, parent_question_id, source_type, type, content, options, answer, explanation, difficulty_score, source_material_id, exam_year, question_number, subquestion_number, source_location, raw_source_text, extraction_method/version, fingerprint, mapping_status/confidence/method/version, segmentation_status, content_quality/content_quality_reason, effective_question_context, is_mapping_eligible, segmentation_is_current, created_at
- `question_study_units`: question_id, study_unit_id, is_primary, relevance_score, is_active, invalidated_reason
- `exam_evidences`: id, question_id, source_material_id, study_unit_id, exam_year, is_primary, relevance_score, confidence, source_location, mapping_method/version, is_active, invalidated_reason, created_at
- `learning_sessions`: id, user_id, course_id, study_unit_id, mode, current_state, started_at, completed_at
- `practice_records`: id, session_id, question_id, user_id, answer, correct, time_spent, created_at
- `learning_records`: id, user_id, course_id, study_unit_id, event_type, metadata, created_at
- `recommendations`: id, user_id, course_id, study_unit_id, reason_type, reason_text, score, created_at
- `events`: id, user_id, course_id, event_type, payload, created_at

## Security
Every course-scoped query must verify ownership. Do not rely on frontend hiding.

## Migration
Use versioned migrations and avoid destructive schema changes during MVP iteration.

Parsing is tracked separately from the worker status: `PARSED`, `LOW_QUALITY`,
`FAILED`, and `UNSUPPORTED` describe whether usable source text exists. The
stored SHA-256 `file_hash` plus `parser_version` is the cache key. The current
SQLite MVP applies additive startup migration for these fields; no old rows or
uploaded files are deleted.

Exam Intelligence uses an additive SQLite startup migration for the Question
provenance/mapping fields and the `exam_evidences` table. A unique fingerprint
makes repeated cached-text processing idempotent. Candidate retrieval is limited
to teaching-derived canonical StudyUnits; REAL_EXAM rows are never KB generators.

Question Intelligence adds a non-destructive quality gate. Segmentation and
content quality are recorded separately from the original question/provenance.
Only `segmentation_status=PASS` with `content_quality=PASS` or
`OCR_NOISY_BUT_USABLE` is mapping eligible. Existing QuestionStudyUnit and
ExamEvidence rows are retained for audit and marked inactive when a rebuild
rejects or refreshes their derived mapping.
