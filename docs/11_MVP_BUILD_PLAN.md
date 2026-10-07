# AI-Exam-Coach — MVP Build Plan

## Priority
- P0: required to run
- P1: core MVP
- P2: enhancement
- V1: after MVP
- V2: later

## Phases
0. **Bootstrap (P0):** repository, Next.js, FastAPI, PostgreSQL, config, logging, README.
1. **Database (P0):** migrations, tables, indexes, foreign keys, seed data.
2. **Backend Foundation (P0):** FastAPI, routing, schemas, services, repositories, errors, API versioning.
3. **Course Creation (P1):** course name, exam date, preferences.
4. **Material Upload (P1):** practical document formats, Bilibili URL, source classification, status.
5. **Background Processing (P0):** worker, status, retry, failure handling.
6. **Course Brain (P1):** parsing, Evidence, Study Units, questions, mapping.
7. **Scoring (P1):** Importance, Difficulty, Mastery, progress metrics.
8. **Home (P1):** dashboard, recommendation, progress, evidence status.
9. **Knowledge (P1):** hierarchy, manual selection, skip, mastered.
10. **Learning (P1):** both modes, sessions, one-question loop.
11. **Practice (P1):** immediate feedback, practice records, mastery updates.
12. **Review (P1):** weak Study Units and reinforcement.
13. **Decision Engine (P1):** priority, recommendation, time-aware strategy.
14. **Time Strategy (P1):** early strengthening, coverage, Final Sprint, short-time fallback.
15. **Explanation (P1):** evidence-grounded explanations, Bilibili where available, PPT/textbook fallback.
16. **Simulation (P2):** optional generated questions, validation, labeling.
17. **UI Polish (P2):** responsive polish and useful micro-interactions.
18. **Integration Test (P0):** Create → Upload → Process → Course Brain → Importance → Recommendation → Learn → Answer → Mastery update → Recommendation → Review.

## MVP acceptance
A real course can be created, evidence processed, Study Units produced, content recommended, both learning modes used, one question shown at a time, answers graded immediately, mastery updated, reinforcement shown, and Final Sprint activated when time is short.

## Do not block MVP on
Advanced memory curves, custom weighting UI, social/gamification, advanced agents, native apps, perfect Bilibili extraction, advanced image question generation.
