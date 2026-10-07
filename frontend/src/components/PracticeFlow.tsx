"use client";

import React from "react";
import { useEffect, useRef, useState } from "react";
import { getNextQuestion, submitQuestionAnswer, userSafeError } from "@/lib/api";
import type { AnswerResult, NextQuestionData } from "@/lib/types";
import { studentStatusLabel } from "@/lib/student-copy";
import Loading from "@/components/State";

export default function PracticeFlow({ sessionId, courseId, onComplete }: { sessionId: string; courseId?: string; onComplete?: () => void }) {
  const [question, setQuestion] = useState<NextQuestionData | null>(null);
  const [feedback, setFeedback] = useState<AnswerResult | null>(null);
  const [chosen, setChosen] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [nextLoading, setNextLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const questionStartedAt = useRef(0);
  const nextRequestInFlight = useRef(false);
  const answerRequestInFlight = useRef(false);

  async function fetchNext() {
    if (nextRequestInFlight.current) return;
    nextRequestInFlight.current = true;
    setNextLoading(true);
    setError("");
    try {
      const result = await getNextQuestion(sessionId);
      if (result.status === "COMPLETE" || !result.question) {
        setQuestion(null);
        setFeedback(null);
        return;
      }
      setQuestion(result);
      setFeedback(null);
      setChosen("");
      setSelected([]);
      questionStartedAt.current = Date.now();
    } catch (requestError) {
      setError(userSafeError(requestError, "暂无可靠练习题"));
      setQuestion(null);
    } finally {
      nextRequestInFlight.current = false;
      setNextLoading(false);
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchNext();
  }, [sessionId]);

  async function submit(text: string) {
    const activeQuestion = question?.question;
    if (!activeQuestion || !text.trim() || answerRequestInFlight.current) return;
    answerRequestInFlight.current = true;
    setSubmitting(true);
    setError("");
    try {
      const result = await submitQuestionAnswer(activeQuestion.id, {
        session_id: sessionId,
        answer: text,
        time_spent: Math.max(1, Math.round((Date.now() - questionStartedAt.current) / 1000)),
      });
      setChosen(text);
      setFeedback(result);
    } catch (requestError) {
      setError(userSafeError(requestError, "答案提交失败，请稍后重试"));
    } finally {
      answerRequestInFlight.current = false;
      setSubmitting(false);
    }
  }

  async function continueLoop() {
    if (!feedback || nextLoading) return;
    if (feedback.next_action === "COMPLETE" || !feedback.next_question_id) {
      setQuestion(null);
      return;
    }
    await fetchNext();
  }

  function optionParts(option: string) {
    const letter = option.split(/[.、．)]/)[0]?.trim() || "A";
    const text = option.replace(/^[A-D][.、．)]\s*/, "").trim();
    return { letter, text: text || option };
  }

  function sourceContext(activeQuestion: NonNullable<NextQuestionData["question"]>) {
    const parts = [] as string[];
    const display = activeQuestion.source_display;
    if (display?.exam_year || activeQuestion.exam_year) parts.push(`${display?.exam_year || activeQuestion.exam_year} 真题`);
    if (display?.question_number || activeQuestion.question_number) parts.push(`第 ${display?.question_number || activeQuestion.question_number} 题`);
    if (display?.label || activeQuestion.source_material_name) parts.push(display?.label || activeQuestion.source_material_name || "课程真题");
    return parts.join(" · ");
  }

  const courseHref = courseId ? `/courses/${courseId}` : "/";
  const exitLink = <a href={courseHref} className="text-sm font-semibold text-secondary">返回课程</a>;

  if (loading) return <Loading text="加载下一题…" />;
  if (error && !question) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
        <div className="absolute right-5 top-5">{exitLink}</div>
        <p className="text-danger">{error}</p>
        <p className="mt-2 text-sm text-muted">本次练习未自动重试，请返回后重新开始。</p>
      </div>
    );
  }
  if (!question?.question) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
        <div className="text-6xl">🎉</div>
        <h1 className="mt-4 text-2xl font-extrabold">本单元已完成</h1>
        <p className="mt-2 text-muted">你已经完成了这个知识点的学习与练习</p>
        {onComplete && <button onClick={onComplete} className="btn-primary mt-8 w-full">继续</button>}
      </div>
    );
  }

  if (feedback) {
    return (
      <div className="flex min-h-[70vh] flex-col px-5 pb-6 pt-6">
        <div className="mb-3 flex items-center justify-between"> <span className="text-xs font-bold text-muted">答题反馈</span>{exitLink}</div>
        <div className={`card flex-1 border-2 ${feedback.correct ? "border-primary" : "border-danger"}`}>
          <div className="flex items-center gap-2">
            <span className="text-3xl">{feedback.correct ? "✅" : "❌"}</span>
            <div>
              <div className="text-lg font-extrabold">{feedback.correct ? "回答正确！" : "回答错误"}</div>
              <div className="text-xs text-muted">
                {studentStatusLabel(feedback.knowledge_update.verified_mastery_status || feedback.knowledge_update.mastery_status)} · 练习得分 {feedback.knowledge_update.practice_score}
              </div>
            </div>
          </div>
          {!feedback.correct && (
            <div className="mt-4 rounded-xl bg-emerald-50 p-3">
              <div className="text-xs font-bold text-emerald-700">正确答案</div>
              <div className="mt-0.5 text-sm font-medium text-emerald-800">{feedback.correct_answer}</div>
            </div>
          )}
          {feedback.teaching_feedback ? (
            <div className="mt-4 rounded-xl bg-slate-50 p-3">
              <div className="text-xs font-bold text-muted">{feedback.teaching_feedback.title}</div>
              <div className="mt-1 text-sm leading-relaxed text-slate-700">{feedback.teaching_feedback.explanation}</div>
              {feedback.teaching_feedback.concept_evidence.length > 0 && (
                <div className="mt-3 space-y-2">
                  {feedback.teaching_feedback.concept_evidence.map((evidence) => (
                    <div key={`${evidence.source}-${evidence.excerpt}`} className="rounded-lg bg-white p-2 text-sm text-slate-700">
                      <div>{evidence.excerpt}</div>
                      {evidence.source && <div className="mt-1 text-xs text-muted">资料：{evidence.source}</div>}
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 text-sm font-semibold text-secondary">{feedback.teaching_feedback.study_unit_title}</div>
              <div className="mt-1 text-sm text-muted">{feedback.teaching_feedback.next_step}</div>
            </div>
          ) : (
            <div className="mt-4">
              <div className="text-xs font-bold text-muted">解析</div>
              <div className="mt-1 text-sm leading-relaxed text-slate-700">{feedback.explanation || "暂无可靠解析"}</div>
            </div>
          )}
          {error && <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
        </div>
        <button onClick={() => void continueLoop()} disabled={nextLoading} className="btn-primary mt-4 w-full disabled:opacity-50">
          {nextLoading ? "加载下一题…" : feedback.next_action === "COMPLETE" ? "完成本单元" : "下一题"}
        </button>
      </div>
    );
  }

  const { question: active, progress } = question;
  const type = active.type || "";
  const hasStructuredOptions = Array.isArray(active.options) && active.options.length >= 2;
  const unsafeQuestion = active.trust_ready === false || ((type === "SINGLE_CHOICE" || type === "MULTIPLE_CHOICE") && !hasStructuredOptions);
  if (unsafeQuestion) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
        <div className="text-5xl">⚠️</div>
        <h1 className="mt-4 text-xl font-extrabold">这道题的题目结构不完整，暂时无法作答。</h1>
        <p className="mt-2 text-sm text-muted">这道题不会提交答案，也不会影响掌握状态。</p>
      </div>
    );
  }
  return (
    <div className="flex min-h-[70vh] flex-col px-5 pb-6 pt-6">
      <div className="mb-3 flex items-center justify-between"> <span className="text-xs font-bold text-muted">本次练习</span>{exitLink}</div>
      <div className="mb-2 flex items-center gap-2">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-primary" style={{ width: `${progress.total_estimated ? (progress.current / progress.total_estimated) * 100 : 0}%` }} />
        </div>
        <span className="text-xs text-muted">{progress.current}/{progress.total_estimated}</span>
      </div>
      <div className="card flex-1">
        {sourceContext(active) && <div className="mb-3 text-xs font-bold text-secondary">{sourceContext(active)}</div>}
        <h1 className="text-lg font-extrabold leading-relaxed text-slate-800">{active.content}</h1>
      </div>
      {error && <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      <div className="mt-4 space-y-2">
        {(type === "SINGLE_CHOICE" || type === "MULTIPLE_CHOICE") && active.options && active.options.length > 0 ? (
          <>
            {active.options.map((option) => {
              const { letter, text } = optionParts(option);
              const multiple = type === "MULTIPLE_CHOICE";
              const selectedNow = selected.includes(letter);
              return (
                <button
                  key={option}
                  onClick={() => (multiple ? setSelected((previous) => previous.includes(letter) ? previous.filter((value) => value !== letter) : [...previous, letter]) : void submit(letter))}
                  disabled={submitting}
                  className={`w-full rounded-xl border-2 bg-white p-3 text-left font-medium ${selectedNow ? "border-primary bg-primary/5" : "border-slate-200"}`}
                >
                  <span className="mr-2 font-bold text-secondary">{letter}</span>{text}
                </button>
              );
            })}
            {type === "MULTIPLE_CHOICE" && (
              <button onClick={() => void submit([...selected].sort().join(""))} disabled={!selected.length || submitting} className="btn-primary w-full disabled:opacity-50">
                {submitting ? "提交中…" : `提交答案（已选 ${selected.join("") || "0"} 项）`}
              </button>
            )}
          </>
        ) : type === "TRUE_FALSE" ? (
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => void submit("T")} disabled={submitting} className="btn-secondary h-20 text-lg font-bold disabled:opacity-50">正确</button>
            <button onClick={() => void submit("F")} disabled={submitting} className="btn-outline h-20 text-lg font-bold disabled:opacity-50">错误</button>
          </div>
        ) : (
          <>
            <textarea value={chosen} onChange={(event) => setChosen(event.target.value)} placeholder="输入你的答案" disabled={submitting} className="min-h-24 w-full rounded-xl border border-slate-300 px-3 py-3 outline-none focus:border-primary" />
            <button onClick={() => void submit(chosen)} disabled={!chosen.trim() || submitting} className="btn-primary w-full disabled:opacity-50">
              {submitting ? "提交中…" : "提交答案"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
