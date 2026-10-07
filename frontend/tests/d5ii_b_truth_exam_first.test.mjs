import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const sessionPage = readFileSync("src/app/learning-sessions/[sessionId]/page.tsx", "utf8");
const rankingPage = readFileSync("src/app/courses/[id]/ranking/page.tsx", "utf8");
const practiceFlow = readFileSync("src/components/PracticeFlow.tsx", "utf8");
const wrongBook = readFileSync("src/app/courses/[id]/wrong-book/page.tsx", "utf8");
const copy = readFileSync("src/lib/student-copy.ts", "utf8");

test("question-first bypasses explanation while explanation-first remains supported", () => {
  assert.match(sessionPage, /session\.mode !== "QUESTION_FIRST"/);
  assert.match(sessionPage, /\/learning-sessions\/\$\{sessionId\}\/explanation/);
});

test("exam focus uses the frozen tier filter and keeps all-items access", () => {
  assert.match(rankingPage, /REAL_EXAM_ACTIVE/);
  assert.match(rankingPage, /全部知识（367）/);
  assert.match(rankingPage, /真题重点（64）/);
});

test("practice UI renders bounded source context and student status copy", () => {
  assert.match(practiceFlow, /exam_year/);
  assert.match(practiceFlow, /question_number/);
  assert.match(practiceFlow, /studentStatusLabel/);
  assert.doesNotMatch(practiceFlow, /raw_source_text/);
});

test("wrong book exposes exact-question retry", () => {
  assert.match(wrongBook, /retryWrongQuestion/);
  assert.match(wrongBook, /重做这道原题/);
  assert.match(wrongBook, /previous_answer/);
});

test("student copy does not require internal enums", () => {
  assert.match(copy, /REAL_EXAM_ACTIVE/);
  assert.match(copy, /真题重点/);
  assert.match(copy, /已通过练习验证/);
});
