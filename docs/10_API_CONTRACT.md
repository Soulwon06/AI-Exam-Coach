# AI-Exam-Coach — API Contract

Base: `/api/v1`

Success: `{"data": {}, "error": null}`
Error: `{"data": null, "error": {"code": "...", "message": "..."}}`

## Courses
- `POST /courses`
- `GET /courses/{course_id}`
- `GET /courses/{course_id}/dashboard`

## Materials
- `POST /courses/{course_id}/materials`
- `POST /courses/{course_id}/materials/url`
- `DELETE /courses/{course_id}/materials/{material_id}`
- `GET /materials/{material_id}`

`DELETE` removes the material and incrementally cleans derived data (orphaned Study Units / Questions / mappings) then re-scores importance. Course is not fully re-analyzed.

Statuses: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

## Knowledge
- `GET /courses/{course_id}/knowledge`
- `GET /study-units/{study_unit_id}`
- `POST /study-units/{study_unit_id}/skip`
- `POST /study-units/{study_unit_id}/master`

## Exam Intelligence

The backend service `evaluation.runner` and persisted Question fields expose the
auditable v1 result without requiring a UI change. Each REAL_EXAM Question keeps
`source_material_id`, year, question/subquestion number, source location,
`raw_source_text`, extraction version, fingerprint, mapping status and
confidence. It also keeps `segmentation_status`, `content_quality`,
`content_quality_reason`, `effective_question_context`, and
`is_mapping_eligible`. Validated primary/secondary links are stored as
`ExamEvidence`; rejected derived links remain auditable but inactive.

## Recommendation
- `GET /courses/{course_id}/recommendation`

Return Study Unit, reason type/text, and estimated time. Recommendation comes from Decision Engine.

## Learning
- `POST /study-units/{study_unit_id}/start`
- `GET /learning-sessions/{session_id}`
- `GET /learning-sessions/{session_id}/explanation`
- `GET /learning-sessions/{session_id}/next-question`
- `POST /questions/{question_id}/answer`

Answer request:
```json
{"session_id":"uuid","answer":"B","time_spent":32}
```

Answer response should include `correct`, `correct_answer`, `explanation`, `knowledge_update`, and `next_action`.

## Review / Progress
- `GET /courses/{course_id}/review`
- `GET /courses/{course_id}/progress`

Progress includes Coverage, Mastery, Important Coverage, Important Mastery.

## Auth
Every course-scoped resource must verify ownership.

## Error codes
`AUTH_REQUIRED`, `FORBIDDEN`, `RESOURCE_NOT_FOUND`, `INVALID_REQUEST`, `COURSE_NOT_READY`, `MATERIAL_PROCESSING`, `MATERIAL_PROCESSING_FAILED`, `AI_PROCESSING_FAILED`, `QUESTION_NOT_AVAILABLE`, `SESSION_EXPIRED`, `INTERNAL_ERROR`.
