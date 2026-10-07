import assert from "node:assert/strict";
import test, { afterEach, beforeEach } from "node:test";
import "./setup-dom";
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import PracticeFlow from "../src/components/PracticeFlow";

let responses: Response[] = [];

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => ({ data }) } as Response;
}

function queue(data: unknown) {
  responses.push(response(data));
}

function activeQuestion(overrides: Record<string, unknown> = {}) {
  return {
    status: "ACTIVE",
    question: {
      id: "q-trust",
      type: "PROBLEM_SOLVING",
      content: "题目",
      options: ["A. 一", "B. 二"],
      is_mapping_eligible: true,
      trust_ready: true,
      objective_signal: true,
      ...overrides,
    },
    progress: { current: 1, total_estimated: 2 },
  };
}

beforeEach(() => {
  responses = [];
  globalThis.fetch = (async () => {
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    return next;
  }) as typeof fetch;
});

afterEach(() => cleanup());

test("unsafe objective question cannot fall back to textarea", async () => {
  queue(activeQuestion({ options: null, trust_ready: false }));
  render(<PracticeFlow sessionId="unsafe-objective" />);
  await waitFor(() => assert.ok(screen.getByText("这道题的题目结构不完整，暂时无法作答。")));
  assert.equal(screen.queryByPlaceholderText("输入你的答案"), null);
  assert.equal(screen.queryByRole("button", { name: "提交答案" }), null);
});

test("objective question normalized by backend renders choices", async () => {
  queue(activeQuestion({ type: "SINGLE_CHOICE", objective_signal: true }));
  render(<PracticeFlow sessionId="normalized-objective" />);
  await waitFor(() => assert.ok(screen.getByText("一")));
  assert.ok(screen.getByText("二"));
  assert.equal(screen.queryByPlaceholderText("输入你的答案"), null);
});

test("valid subjective question keeps textarea", async () => {
  queue(activeQuestion({ type: "SHORT_ANSWER", options: null, objective_signal: false }));
  render(<PracticeFlow sessionId="valid-subjective" />);
  await waitFor(() => assert.ok(screen.getByPlaceholderText("输入你的答案")));
});

test("trusted short-answer question with a weak objective signal remains answerable", async () => {
  queue(activeQuestion({
    type: "SHORT_ANSWER",
    options: null,
    trust_ready: true,
    objective_signal: true,
    trust_confidence: "MEDIUM",
  }));
  render(<PracticeFlow sessionId="valid-short-answer-objective-signal" />);
  await waitFor(() => assert.ok(screen.getByPlaceholderText("输入你的答案")));
  assert.ok(screen.getByRole("button", { name: "提交答案" }));
  assert.equal(screen.queryByText("这道题的题目结构不完整，暂时无法作答。"), null);
});

test("unusable backend explanation is shown as a safe fallback", async () => {
  queue(activeQuestion({ type: "SINGLE_CHOICE", objective_signal: true }));
  queue({ correct: false, correct_answer: "B", explanation: null, knowledge_update: { mastery_status: "REVIEW", practice_score: 0 }, next_action: "COMPLETE", next_question_id: null });
  render(<PracticeFlow sessionId="bad-explanation" />);
  await waitFor(() => assert.ok(screen.getByText("一")));
  const option = screen.getByText("二");
  option.click();
  await waitFor(() => assert.ok(screen.getByText("暂无可靠解析")));
});
