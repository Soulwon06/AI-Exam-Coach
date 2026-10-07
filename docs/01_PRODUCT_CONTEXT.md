# AI-Exam-Coach — Product Context

**Status: MVP specification frozen.**

AI-Exam-Coach is an AI-assisted university final-exam review system. It helps students decide what to study first, what can be deprioritized, and what should be reinforced before the exam.

It is not a generic chatbot. Its core is:
1. Course Brain
2. Scoring Engine
3. Decision Engine
4. Practice Loop

## Core loop
Create Course → Upload Evidence → Build Course Brain → Create Study Units → Calculate Importance → Recommend → Learn → Practice → Update Student State → Recommend Again.

## Evidence
Recommended: real exam papers, exam scope, teacher PPT, textbook.
Optional: Bilibili, class notes, homework, lab materials, other evidence.

These are different evidence types, not interchangeable generic “materials”.

## Core product decisions
- Real exam evidence has the strongest default authority.
- User-facing learning units are called “知识点”; backend uses `StudyUnit`.
- AI recommends, but students can manually choose knowledge.
- One question at a time; immediate grading.
- Skip and Mastered are different states.
- Simulation is optional and P2.
- Final Sprint must remain available for reinforcing the most important knowledge even if coverage is incomplete.
