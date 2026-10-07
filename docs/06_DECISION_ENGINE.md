# AI-Exam-Coach — Decision Engine

## Purpose
Choose what the student should study next under time constraints.

## Inputs
Importance, Mastery/Weakness, Urgency, Coverage, remaining time, preferences, current learning state.

Conceptually: `Priority = f(Importance, Weakness, Urgency, Coverage, RemainingTime)`.

## Manual override
When a user explicitly chooses a Study Unit, start it and do not replace it with an AI recommendation during that session. Resume normal recommendation afterward.

## Time strategy
- Earlier: emphasize important + weak knowledge.
- Around four days before the exam in a seven-day example: increase coverage.
- Around two days before: Final Sprint, emphasizing important + weak knowledge.
- One or two days remaining: move directly toward Final Sprint behavior.

The seven-day schedule is an example strategy, not a fixed calendar.

## Skip
Reduces current recommendation pressure; does not mean mastered.

## Mastered
Reduces reinforcement pressure until later practice indicates weakness.

## Recommendation
`GET /courses/{course_id}/recommendation` returns Study Unit, human-readable reason, and estimated time.
