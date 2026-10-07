# AI-Exam-Coach — Scoring Engine

## Signals
### Importance
How important a Study Unit is for the exam. Inputs may include real-exam frequency/coverage, exam scope, teacher emphasis, and supporting evidence. Real-exam evidence has strongest default influence.

### Difficulty
How difficult a Study Unit or question is.

### Mastery
How well the current student knows a Study Unit. Inputs include recent accuracy, repeated errors, practice history, and explicit Mastered state.

A student error primarily changes Mastery/Weakness, not exam Importance.

## UI labels
Use `HIGH`, `MEDIUM`, `LOW` or human-readable labels such as 高频/重点/一般. Do not expose raw scores.

## Configuration
Use `DEFAULT_IMPORTANCE_WEIGHTS`. Avoid double-counting correlated evidence such as frequency and coverage.

MVP: default weights only.
V1: user-adjustable weights.

## Progress
Backend maintains Coverage, Mastery, Important Coverage, Important Mastery. UI may show only a subset.
