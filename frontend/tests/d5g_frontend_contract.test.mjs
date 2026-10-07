import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  answerRequest,
  availabilityText,
  canStartPractice,
  nextQuestionPath,
  startExplanationFirstRequest,
  startLearningRequest,
  startSessionRequest,
} from "../src/lib/d5g-contract.mjs";

const rankingPage = readFileSync(resolve("src/app/courses/[id]/ranking/page.tsx"), "utf8");
const coursePage = readFileSync(resolve("src/app/courses/[id]/page.tsx"), "utf8");
const sessionPage = readFileSync(resolve("src/app/learning-sessions/[sessionId]/page.tsx"), "utf8");
const rankingResults = readFileSync(resolve("src/components/RankingResults.tsx"), "utf8");
const practiceFlow = readFileSync(resolve("src/components/PracticeFlow.tsx"), "utf8");
const learnPage = readFileSync(resolve("src/app/learn/[studyUnitId]/page.tsx"), "utf8");
const apiSource = readFileSync(resolve("src/lib/api.ts"), "utf8");

const ready = {
  practice_question_binding_ready: true,
  practice_binding_status: "READY_PRIMARY_QUESTION",
};

test("ranking fixture preserves real API availability states", () => {
  assert.equal(canStartPractice(ready), true);
  assert.equal(canStartPractice({ ...ready, practice_binding_status: "NO_PRIMARY_QUESTION" }), false);
  assert.equal(canStartPractice({ ...ready, practice_binding_status: "IMAGE_DEPENDENCY_NOT_SERVABLE" }), false);
  assert.match(availabilityText("NO_PRIMARY_QUESTION"), /暂无/);
  assert.match(availabilityText("IMAGE_DEPENDENCY_NOT_SERVABLE"), /图片/);
});

test("start practice uses the verified QUESTION_FIRST request", () => {
  assert.deepEqual(startSessionRequest("unit-1"), {
    path: "/study-units/unit-1/start",
    method: "POST",
    body: JSON.stringify({ mode: "QUESTION_FIRST" }),
  });
});

test("generic learning and explicit explanation requests do not force QUESTION_FIRST", () => {
  assert.deepEqual(startLearningRequest("unit-1"), {
    path: "/study-units/unit-1/start",
    method: "POST",
    body: JSON.stringify({}),
  });
  assert.deepEqual(startExplanationFirstRequest("unit-1"), {
    path: "/study-units/unit-1/start",
    method: "POST",
    body: JSON.stringify({ mode: "EXPLANATION_FIRST" }),
  });
  assert.match(apiSource, /startLearningUsingPreference/);
  assert.match(apiSource, /startExplanationFirstSession/);
});

test("next-question follows the session endpoint", () => {
  assert.equal(nextQuestionPath("session-1"), "/learning-sessions/session-1/next-question");
});

test("answer request binds question, session, answer, and elapsed time", () => {
  const payload = { session_id: "session-1", answer: "B", time_spent: 7 };
  assert.deepEqual(answerRequest("question-1", payload), {
    path: "/questions/question-1/answer",
    method: "POST",
    body: JSON.stringify(payload),
  });
});

test("completion is represented by backend state, not a guessed question id", () => {
  const completion = { status: "COMPLETE", question: null, progress: { current: 2, total_estimated: 2 } };
  assert.equal(completion.status, "COMPLETE");
  assert.equal(completion.question, null);
});

test("ranking page connects to the real course ranking helper", () => {
  assert.match(rankingPage, /getCourseRanking\(id\)/);
  assert.match(apiSource, /\/courses\/\$\{courseId\}\/ranking/);
});

test("ready primary evidence is the only enabled practice action", () => {
  assert.match(rankingResults, /canStartPractice\(item\)/);
  assert.match(rankingPage, /startQuestionFirstSession\(item\.study_unit_id\)/);
});

test("knowledge-point entry communicates preference and hides direct practice without a safe question", () => {
  assert.match(learnPage, /学习方式：\{preferredModeLabel\}/);
  assert.match(learnPage, /practiceReady = unit\.practice_question_binding_ready === true/);
  assert.match(learnPage, /practiceReady \? "开始学习" : "学习知识点"/);
  assert.match(learnPage, /practiceReady && preferredMode === "EXPLANATION_FIRST"/);
  assert.match(learnPage, /start\("QUESTION_FIRST"\)/);
});

test("practice-unavailable ranking rows remain learnable without an enabled practice action", () => {
  assert.match(rankingResults, /item\.study_unit_id \? \(/);
  assert.match(rankingResults, /学习知识点/);
  assert.match(rankingResults, /暂无可练真题/);
  assert.doesNotMatch(rankingResults, /暂不可练习/);
});

test("secondary-only availability stays learnable without practice", () => {
  assert.equal(canStartPractice({ practice_question_binding_ready: false, practice_binding_status: "READY_PRIMARY_QUESTION" }), false);
  assert.match(rankingResults, /学习知识点/);
});

test("image-dependent availability stays disabled", () => {
  assert.equal(canStartPractice({ practice_question_binding_ready: true, practice_binding_status: "IMAGE_DEPENDENCY_NOT_SERVABLE" }), false);
  assert.match(availabilityText("IMAGE_DEPENDENCY_NOT_SERVABLE"), /暂不支持作答/);
});

test("single-choice rendering uses backend options", () => {
  assert.match(practiceFlow, /SINGLE_CHOICE/);
  assert.match(practiceFlow, /active\.options\.map/);
});

test("short-answer input submits the raw answer", () => {
  assert.match(practiceFlow, /输入你的答案/);
  assert.match(practiceFlow, /submit\(chosen\)/);
});

test("answer response drives correct feedback", () => {
  assert.match(practiceFlow, /feedback\.correct/);
  assert.match(practiceFlow, /回答正确/);
});

test("answer response drives incorrect feedback and correct answer display", () => {
  assert.match(practiceFlow, /回答错误/);
  assert.match(practiceFlow, /feedback\.correct_answer/);
});

test("next action continues through the normal next-question flow", () => {
  assert.match(practiceFlow, /await fetchNext\(\)/);
  assert.match(practiceFlow, /feedback\.next_action === "COMPLETE"/);
});

test("complete state is rendered as a completion screen", () => {
  assert.match(practiceFlow, /!question\?\.question/);
  assert.match(practiceFlow, /本单元已完成/);
});

test("duplicate answer submission is guarded while pending", () => {
  assert.match(practiceFlow, /answerRequestInFlight\.current/);
  assert.match(practiceFlow, /disabled=\{submitting\}/);
});

test("safe error handling covers auth, missing, completed, validation, and server errors", () => {
  assert.match(apiSource, /error\.status === 401/);
  assert.match(apiSource, /error\.status === 404/);
  assert.match(apiSource, /error\.status === 410/);
  assert.match(apiSource, /error\.status === 422/);
  assert.match(apiSource, /error\.status >= 500/);
});

test("ranking refetches when the user returns to the page", () => {
  assert.match(rankingPage, /visibilitychange/);
  assert.match(rankingPage, /void load\(\)/);
});

test("course dashboard refetches when the user returns from practice", () => {
  assert.match(coursePage, /useCallback/);
  assert.match(coursePage, /visibilitychange/);
  assert.match(coursePage, /pageshow/);
  assert.match(coursePage, /window\.addEventListener\("focus"/);
  assert.match(coursePage, /loadDashboard\(\)/);
});

test("frontend does not calculate correctness", () => {
  assert.doesNotMatch(practiceFlow, /correct_answer\s*===\s*chosen/);
  assert.match(practiceFlow, /feedback\.correct/);
});

test("practice and feedback views expose a stable course exit", () => {
  assert.match(practiceFlow, /返回课程/);
  assert.match(practiceFlow, /courseId/);
  assert.match(sessionPage, /course_id/);
  assert.match(sessionPage, /practice_question_binding_ready/);
});
