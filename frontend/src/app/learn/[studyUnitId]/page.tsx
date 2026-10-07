"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, masterStudyUnit, skipStudyUnit, startExplanationFirstSession, startLearningUsingPreference, startQuestionFirstSession, userSafeError } from "@/lib/api";
import type { RecommendationStudyUnit } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

export default function LearnPage() {
  const { studyUnitId } = useParams<{ studyUnitId: string }>();
  const router = useRouter();
  const [unit, setUnit] = useState<RecommendationStudyUnit | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [actionStatus, setActionStatus] = useState<"MASTERED" | "SKIPPED" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const u = await api<RecommendationStudyUnit>(`/study-units/${studyUnitId}`);
        setUnit(u);
        if (u.self_assessed_mastery) setActionStatus("MASTERED");
        else if (u.study_preference === "DEFERRED") setActionStatus("SKIPPED");
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [studyUnitId]);

  async function start(intent: "PREFERENCE" | "QUESTION_FIRST" | "EXPLANATION_FIRST") {
    setStarting(true);
    try {
      if (unit?.active_session_id) {
        router.push(`/learning-sessions/${unit.active_session_id}`);
        return;
      }
      const startRequest = intent === "QUESTION_FIRST"
        ? startQuestionFirstSession
        : intent === "EXPLANATION_FIRST"
          ? startExplanationFirstSession
          : startLearningUsingPreference;
      const r = await startRequest(studyUnitId);
      router.push(`/learning-sessions/${r.session_id}`);
    } catch (e) {
      setError(userSafeError(e, "启动失败"));
      setStarting(false);
    }
  }

  async function markMastered() {
    if (actionPending || !unit) return;
    setActionPending(true);
    setError("");
    try {
      await masterStudyUnit(studyUnitId);
      setUnit((current) => (current ? { ...current, self_assessed_mastery: true } : current));
      setActionStatus("MASTERED");
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setActionPending(false);
    }
  }

  async function skip() {
    if (actionPending || !unit) return;
    setActionPending(true);
    setError("");
    try {
      await skipStudyUnit(studyUnitId);
      setUnit((current) => (current ? { ...current, study_preference: "DEFERRED" } : current));
      setActionStatus("SKIPPED");
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setActionPending(false);
    }
  }

  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="px-4 pt-16 text-center">
        <p className="text-danger">{error}</p>
        <Link href="/" className="btn-outline mt-4 inline-block">
          返回
        </Link>
      </div>
    );
  }
  if (!unit) return null;

  const importance = unit.exam_evidence_tier === "REAL_EXAM_ACTIVE"
    ? "真题重点"
    : unit.canonical_graph_version
      ? "统一知识图谱"
      : unit.importance_label === "HIGH" ? "高频考点" : unit.importance_label === "MEDIUM" ? "重点内容" : "一般内容";
  const practiceReady = unit.practice_question_binding_ready === true;
  const preferredMode = unit.learning_mode === "QUESTION_FIRST" ? "QUESTION_FIRST" : "EXPLANATION_FIRST";
  const preferredModeLabel = preferredMode === "QUESTION_FIRST" ? "先做题再讲" : "先学后练";
  const startLabel = unit.active_session_id
    ? "继续学习"
    : unit.coverage_status === "PARTIAL"
      ? "完成剩余练习"
      : practiceReady ? "开始学习" : "学习知识点";

  return (
    <div className="flex min-h-[70vh] flex-col justify-center px-4 pt-8">
      <div className="card text-center">
        <div className="text-4xl">🎯</div>
        <h1 className="mt-3 text-lg font-extrabold text-slate-800">{unit.title}</h1>
        <p className="mt-1 text-sm text-muted">{importance}</p>
        <div className="mt-3 rounded-lg bg-bg px-3 py-2 text-sm font-semibold text-secondary">
          学习方式：{preferredModeLabel}
        </div>
        {!practiceReady && (
          <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-left text-sm text-amber-800">
            {preferredMode === "QUESTION_FIRST"
              ? "你通常选择先做题，但这个知识点当前没有可练题，先看看讲解。"
              : "当前暂无可安全作答的练习题，可以先学习这个知识点。"}
          </div>
        )}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-bg py-3">
            <div className="text-lg font-extrabold text-slate-800">{unit.estimated_minutes}</div>
            <div className="text-xs text-muted">预计分钟</div>
          </div>
          <div className="rounded-xl bg-bg py-3">
            <div className="text-lg font-extrabold text-slate-800">{Math.round(unit.mastery_percent ?? unit.progress)}%</div>
            <div className="text-xs text-muted">练习正确率</div>
          </div>
        </div>
        {error && <p className="mt-4 text-sm text-danger">{error}</p>}

        {actionStatus === "SKIPPED" ? (
          <>
            <div className="mt-6 rounded-xl bg-bg px-3 py-3 text-sm font-semibold text-slate-700">
              已暂时跳过，可以随时恢复学习
            </div>
            <button onClick={() => void start(practiceReady ? "PREFERENCE" : "EXPLANATION_FIRST")} disabled={starting || actionPending} className="btn-primary mt-3 w-full disabled:opacity-50">
              {starting ? "准备中…" : "恢复学习"}
            </button>
            <button onClick={() => router.back()} className="btn-outline mt-3 w-full">返回课程</button>
          </>
        ) : actionStatus === "MASTERED" ? (
          <>
            <div className="mt-6 rounded-xl bg-bg px-3 py-3 text-sm font-semibold text-slate-700">
              已记录自评掌握；系统验证进度仍以练习结果为准
            </div>
            <button onClick={() => void start(practiceReady ? "QUESTION_FIRST" : "EXPLANATION_FIRST")} disabled={starting || actionPending} className="btn-primary mt-3 w-full disabled:opacity-50">继续练习</button>
            <button onClick={() => router.back()} className="btn-outline mt-3 w-full">返回课程</button>
          </>
        ) : (
          <>
            <button onClick={() => void start(practiceReady ? "PREFERENCE" : "EXPLANATION_FIRST")} disabled={starting || actionPending} className="btn-primary mt-6 w-full disabled:opacity-50">
              {starting ? "准备中…" : startLabel}
            </button>
            <div className={`mt-3 grid ${practiceReady ? "grid-cols-2" : "grid-cols-1"} gap-3`}>
              {practiceReady && preferredMode === "EXPLANATION_FIRST" && (
                <button onClick={() => void start("QUESTION_FIRST")} disabled={actionPending || starting} className="btn-outline disabled:opacity-50">
                  直接做题
                </button>
              )}
              {practiceReady && preferredMode === "QUESTION_FIRST" && (
                <button onClick={() => void start("EXPLANATION_FIRST")} disabled={actionPending || starting} className="btn-outline disabled:opacity-50">
                  先看讲解
                </button>
              )}
              <button onClick={markMastered} disabled={actionPending || starting} className="btn-secondary disabled:opacity-50">
                {actionPending ? "处理中…" : "已掌握"}
              </button>
              <button onClick={skip} disabled={actionPending || starting} className="btn-outline disabled:opacity-50">
                暂时跳过
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
