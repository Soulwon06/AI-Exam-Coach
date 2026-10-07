# AI-Exam-Coach — Frontend Specification

## Stack
Next.js, TypeScript, Tailwind CSS, mobile-first responsive UI.

## Routes
- `/course/new`
- `/courses/:id/preparing`
- `/courses/:id`
- `/courses/:id/knowledge`
- `/courses/:id/review`
- `/courses/:id/settings`
- `/learn/:studyUnitId`
- `/learning-sessions/:sessionId`

## Course Creation
Course name, exam date, optional school/teacher, learning mode, simulation preference, evidence upload/link. Primary CTA: `创建课程`.

## Material Management (`/courses/:id/preparing`)
Uploaded material list shows each item's name and processing status with a delete button. Deleting asks for confirmation, then incrementally rebuilds affected knowledge without a full re-analysis. Can be reached both during creation and after the course is ready.

## Home
Show course name, days remaining, progress, important-content progress, evidence status, current recommendation. Primary CTA: `开始学习`.

## Knowledge
Knowledge Domain → Study Unit. Allow manual selection, skip, and mastered.

## Learning
Hide bottom navigation during active answering. Support Explanation First and Question First. One question at a time; immediate grading; no batch submission.

## Review
Show Study Units needing reinforcement.

## Navigation
Mobile bottom navigation: 学习 / 知识 / 错题/强化 / 我的.

## UI direction
Duolingo-inspired principles: progression, cards, immediate feedback, visible progress, low cognitive load. Do not copy branding. No XP/streaks/leaderboards/badges in MVP.
