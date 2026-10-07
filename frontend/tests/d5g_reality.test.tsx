import assert from "node:assert/strict";
import test, { afterEach, beforeEach } from "node:test";
import "./setup-dom";
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RankingResults from "../src/components/RankingResults";
import PracticeFlow from "../src/components/PracticeFlow";
import * as api from "../src/lib/api";
import type { RankingItem } from "../src/lib/types";

type FetchCall = { url: string; init?: RequestInit };
let calls: FetchCall[] = [];
let responses: Array<Response | Promise<Response>> = [];

function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => (status >= 200 && status < 300 ? { data } : { error: { code: `HTTP_${status}`, message: `backend ${status}` } }),
  } as Response;
}

function queue(data: unknown, status = 200) {
  responses.push(response(data, status));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
  return { promise, resolve };
}

const readyItem = {
  canonical_kp_id: "kp-ready",
  ranking_position: 1,
  title: "Ready point",
  study_unit_id: "unit-ready",
  practice_question_binding_ready: true,
  practice_binding_status: "READY_PRIMARY_QUESTION" as const,
};

const question = (type: string, id = "question-1", options?: string[]) => ({
  status: "ACTIVE" as const,
  question: { id, type, content: `${type} content`, options, is_mapping_eligible: true },
  progress: { current: 1, total_estimated: 2 },
});

beforeEach(() => {
  calls = [];
  responses = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    return next;
  }) as typeof fetch;
  localStorage.clear();
});

afterEach(() => cleanup());

test("API client executes ranking, start, next, and answer requests at fetch boundary", async () => {
  queue({ items: [readyItem], total: 1, filtered_total: 1, offset: 0, limit: 367, policy_version: "v", ranking_view: "default" });
  const ranking = await api.getCourseRanking("course-1");
  assert.equal(ranking.items[0].study_unit_id, "unit-ready");
  assert.match(calls[0].url, /\/api\/v1\/courses\/course-1\/ranking\?offset=0&limit=367$/);
  assert.equal(calls[0].init?.credentials, "include");
  assert.equal((calls[0].init?.headers as Record<string, string>)?.["X-User-Id"], undefined);
  assert.equal(api.getUserId(), "");

  queue({ session_id: "session-1", state: "ACTIVE" });
  await api.startQuestionFirstSession("unit-ready");
  assert.equal(calls[1].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { mode: "QUESTION_FIRST" });

  queue(question("SINGLE_CHOICE"));
  await api.getNextQuestion("session-1");
  assert.equal(calls[2].url, "/api/v1/learning-sessions/session-1/next-question");

  queue({ correct: true, correct_answer: "A", explanation: "ok", knowledge_update: { mastery_status: "LEARNING", practice_score: 1 }, next_action: "NEXT_QUESTION", next_question_id: "question-2" });
  const answer = await api.submitQuestionAnswer("question-1", { session_id: "session-1", answer: "A", time_spent: 4 });
  assert.equal(answer.correct, true);
  assert.equal(calls[3].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[3].init?.body)), { session_id: "session-1", answer: "A", time_spent: 4 });
});

test("API client propagates backend errors without retrying", async () => {
  queue(null, 422);
  await assert.rejects(() => api.getNextQuestion("session-error"), (error: unknown) => error instanceof api.ApiError && error.status === 422);
  assert.equal(calls.length, 1);
});

test("ranking production component renders ready action and calls start handler", async () => {
  const onStart = (item: RankingItem) => { calls.push({ url: `started:${item.study_unit_id}` }); };
  render(<RankingResults data={{ items: [readyItem], total: 1, filtered_total: 1, offset: 0, limit: 367, policy_version: "v", ranking_view: "default" }} loading={false} error="" onRetry={() => undefined} startingId={null} onStart={onStart} />);
  const button = screen.getByRole("button", { name: "开始练习" });
  assert.equal((button as HTMLButtonElement).disabled, false);
  fireEvent.click(button);
  assert.equal(calls.at(-1)?.url, "started:unit-ready");
});

test("ranking production component keeps unavailable rows learnable without practice", () => {
  const rows = [
    { ...readyItem, canonical_kp_id: "kp-none", practice_binding_status: "NO_PRIMARY_QUESTION" as const },
    { ...readyItem, canonical_kp_id: "kp-image", practice_binding_status: "IMAGE_DEPENDENCY_NOT_SERVABLE" as const },
    { ...readyItem, canonical_kp_id: "kp-secondary", practice_question_binding_ready: false },
  ];
  render(<RankingResults data={{ items: rows, total: 3, filtered_total: 3, offset: 0, limit: 367, policy_version: "v", ranking_view: "default" }} loading={false} error="" onRetry={() => undefined} startingId={null} onStart={() => { throw new Error("unavailable row started"); }} />);
  assert.equal(screen.getAllByRole("link", { name: "学习知识点" }).length, 3);
  assert.match(screen.getByText("当前暂无可直接练习的主关联真题").textContent || "", /暂无/);
  assert.match(screen.getByText("该真题依赖图片，当前版本暂不支持作答").textContent || "", /图片/);
});

test("ranking production component renders loading, error, and empty states", () => {
  const props = { onRetry: () => undefined, startingId: null, onStart: () => undefined };
  const loadingView = render(<RankingResults {...props} data={null} loading={true} error="" />);
  assert.match(loadingView.container.textContent || "", /加载真实知识点排名/);
  loadingView.unmount();
  const errorView = render(<RankingResults {...props} data={null} loading={false} error="安全错误" />);
  assert.match(errorView.container.textContent || "", /安全错误/);
  errorView.unmount();
  const emptyView = render(<RankingResults {...props} data={{ items: [], total: 0, filtered_total: 0, offset: 0, limit: 367, policy_version: "v", ranking_view: "default" }} loading={false} error="" />);
  assert.match(emptyView.container.textContent || "", /暂无可展示/);
});

test("practice production component renders SINGLE_CHOICE options", async () => {
  queue(question("SINGLE_CHOICE", "single-1", ["A. Alpha", "B. Beta"]));
  render(<PracticeFlow sessionId="session-single" />);
  await waitFor(() => assert.ok(screen.getByText("Alpha")));
  assert.ok(screen.getByText("Beta"));
});

test("practice production component renders SHORT_ANSWER textarea", async () => {
  queue(question("SHORT_ANSWER", "short-1"));
  render(<PracticeFlow sessionId="session-short" />);
  await waitFor(() => assert.ok(screen.getByPlaceholderText("输入你的答案")));
  assert.equal(screen.getByRole("textbox").tagName, "TEXTAREA");
});

test("practice production component renders TRUE_FALSE choices", async () => {
  queue(question("TRUE_FALSE", "tf-1"));
  render(<PracticeFlow sessionId="session-tf" />);
  await waitFor(() => assert.ok(screen.getByRole("button", { name: "正确" })));
  assert.ok(screen.getByRole("button", { name: "错误" }));
});

test("practice production component allows MULTIPLE_CHOICE selections", async () => {
  queue(question("MULTIPLE_CHOICE", "multi-1", ["A. Alpha", "B. Beta"]));
  render(<PracticeFlow sessionId="session-multi" />);
  await waitFor(() => assert.ok(screen.getByText("Alpha")));
  await userEvent.click(screen.getByText("Alpha"));
  await userEvent.click(screen.getByText("Beta"));
  assert.match(screen.getByRole("button", { name: /已选 AB/ }).textContent || "", /AB/);
});

test("practice answer executes API path and renders correct authoritative feedback", async () => {
  queue(question("SINGLE_CHOICE", "answer-1", ["A. Alpha", "B. Beta"]));
  queue({ correct: true, correct_answer: "B", explanation: "Because", knowledge_update: { mastery_status: "MASTERED", practice_score: 1 }, next_action: "COMPLETE", next_question_id: null });
  render(<PracticeFlow sessionId="session-answer" />);
  await waitFor(() => assert.ok(screen.getByText("Beta")));
  await userEvent.click(screen.getByText("Beta"));
  await waitFor(() => assert.ok(screen.getByText("回答正确！")));
  assert.equal(calls[1].url, "/api/v1/questions/answer-1/answer");
  const payload = JSON.parse(String(calls[1].init?.body));
  assert.equal(payload.session_id, "session-answer");
  assert.equal(payload.answer, "B");
  assert.equal(typeof payload.time_spent, "number");
  assert.match(screen.getByText("Because").textContent || "", /Because/);
  assert.match(screen.getByText(/已通过练习验证/).textContent || "", /已通过练习验证/);
});

test("practice answer pending disables submit and prevents duplicate mutation", async () => {
  queue(question("SHORT_ANSWER", "pending-1"));
  const answerWait = deferred<Response>();
  responses.push(answerWait.promise);
  render(<PracticeFlow sessionId="session-pending" />);
  await waitFor(() => assert.ok(screen.getByPlaceholderText("输入你的答案")));
  await userEvent.type(screen.getByRole("textbox"), "answer");
  const submit = screen.getByRole("button", { name: "提交答案" });
  await userEvent.click(submit);
  await waitFor(() => assert.ok(screen.getByText("提交中…")));
  assert.equal(calls.length, 2);
  assert.equal((screen.getByRole("button", { name: "提交中…" }) as HTMLButtonElement).disabled, true);
  answerWait.resolve(response({ correct: true, correct_answer: "answer", knowledge_update: { mastery_status: "LEARNING", practice_score: 1 }, next_action: "COMPLETE", next_question_id: null }));
});

test("incorrect feedback renders backend answer, explanation, and mastery update", async () => {
  queue(question("SINGLE_CHOICE", "wrong-1", ["A. Alpha", "B. Beta"]));
  queue({ correct: false, correct_answer: "A", explanation: "Review the rule", knowledge_update: { mastery_status: "WEAK", practice_score: 0 }, next_action: "COMPLETE", next_question_id: null });
  render(<PracticeFlow sessionId="session-wrong" />);
  await waitFor(() => assert.ok(screen.getByText("Alpha")));
  await userEvent.click(screen.getByText("Beta"));
  await waitFor(() => assert.ok(screen.getByText("回答错误")));
  assert.ok(screen.getByText("正确答案"));
  assert.ok(screen.getByText("A"));
  assert.ok(screen.getByText("Review the rule"));
  assert.match(screen.getByText(/需要加强/).textContent || "", /需要加强/);
});

test("NEXT_QUESTION uses normal endpoint and exposes pending UI without duplicate GET", async () => {
  queue(question("SINGLE_CHOICE", "next-1", ["A. Alpha", "B. Beta"]));
  queue({ correct: true, correct_answer: "A", knowledge_update: { mastery_status: "LEARNING", practice_score: 1 }, next_action: "NEXT_QUESTION", next_question_id: "next-2" });
  const nextWait = deferred<Response>();
  responses.push(nextWait.promise);
  render(<PracticeFlow sessionId="session-next" />);
  await waitFor(() => assert.ok(screen.getByText("Alpha")));
  await userEvent.click(screen.getByText("Alpha"));
  await waitFor(() => assert.ok(screen.getByText("下一题")));
  const nextButton = screen.getByRole("button", { name: "下一题" });
  await userEvent.click(nextButton);
  await waitFor(() => assert.ok(screen.getByText("加载下一题…")));
  await userEvent.click(screen.getByRole("button", { name: "加载下一题…" }));
  assert.equal(calls.filter((call) => call.url.includes("next-question")).length, 2);
  nextWait.resolve(response(question("SINGLE_CHOICE", "next-2", ["A. Next", "B. Later"])));
  await waitFor(() => assert.ok(screen.getByText("Next")));
});

test("COMPLETE renders completion and does not refetch", async () => {
  queue({ status: "COMPLETE", question: null, progress: { current: 2, total_estimated: 2 } });
  render(<PracticeFlow sessionId="session-complete" />);
  await waitFor(() => assert.ok(screen.getByText("本单元已完成")));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls.filter((call) => call.url.includes("next-question")).length, 1);
});

test("404 and 500-style errors render safely without answer auto-retry", async () => {
  queue(null, 404);
  render(<PracticeFlow sessionId="session-404" />);
  await waitFor(() => assert.ok(screen.getByText("内容暂时不可用，请返回后重试")));
  cleanup();
  calls = [];
  responses = [];
  queue(question("SHORT_ANSWER", "error-answer"));
  queue(null, 500);
  render(<PracticeFlow sessionId="session-500" />);
  await waitFor(() => assert.ok(screen.getByPlaceholderText("输入你的答案")));
  await userEvent.type(screen.getByRole("textbox"), "answer");
  await userEvent.click(screen.getByRole("button", { name: "提交答案" }));
  await waitFor(() => assert.ok(screen.getByText("服务暂时不可用，请稍后重试")));
  assert.equal(calls.filter((call) => call.url.includes("/answer")).length, 1);
});
