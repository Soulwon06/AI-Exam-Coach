"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, userSafeError } from "@/lib/api";
import type { ExplanationData, SessionData } from "@/lib/types";
import Loading from "@/components/State";
import PracticeFlow from "@/components/PracticeFlow";

type Stage = "explanation" | "practice";

export default function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("practice");
  const [sessionInfo, setSessionInfo] = useState<SessionData | null>(null);
  const [explanation, setExplanation] = useState<ExplanationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const session = await api<SessionData>(`/learning-sessions/${sessionId}`);
        setSessionInfo(session);
        if (session.state !== "COMPLETED" && session.mode !== "QUESTION_FIRST") {
          try {
            setExplanation(await api<ExplanationData>(`/learning-sessions/${sessionId}/explanation`));
            setStage("explanation");
          } catch {
            setStage("practice");
          }
        }
      } catch (requestError) {
        setError(userSafeError(requestError, "练习加载失败"));
      } finally {
        setLoading(false);
      }
    })();
  }, [sessionId]);

  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
        <p className="text-danger">{error}</p>
      </div>
    );
  }

  const courseHref = sessionInfo?.course_id ? `/courses/${sessionInfo.course_id}` : "/";

  if (stage === "practice" || !explanation) return <PracticeFlow sessionId={sessionId} courseId={sessionInfo?.course_id} onComplete={() => router.back()} />;

  const evidenceLabel = {
    EXPLANATION_EVIDENCE: "已绑定教材正文证据",
    STRUCTURE_ONLY: "仅找到章节结构证据，暂无充分正文讲解",
    GENERIC_FALLBACK: "暂无可用的来源讲解证据",
  }[explanation.explanation_mode || "GENERIC_FALLBACK"];

  return (
    <div className="flex min-h-[90vh] flex-col px-5 pb-6 pt-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-xs font-bold uppercase tracking-wider text-muted">先讲后练 · 知识点讲解</div>
        <Link href={courseHref} className="text-sm font-semibold text-secondary">返回课程</Link>
      </div>
      <div className="card flex-1 overflow-y-auto">
        <h1 className="text-lg font-extrabold text-slate-800">{explanation.title}</h1>
        <div className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-muted" role="status">{evidenceLabel}</div>
        <div className="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed text-slate-700">
          {explanation.content.replace(/^### /, "").split("\n").map((line, index) =>
            line.startsWith("- ") ? <li key={index} className="ml-4 list-disc">{line.slice(2)}</li> : <p key={index} className="mb-2">{line}</p>,
          )}
        </div>
        {explanation.sources.length > 0 && <div className="mt-4 text-xs text-muted">来源：{explanation.sources.map((source) => source.display_label || source.source_file || "课程资料").join("、")}</div>}
      </div>
      {sessionInfo?.practice_question_binding_ready === false ? (
        <Link href={courseHref} className="btn-primary mt-4 block w-full text-center">返回课程</Link>
      ) : (
        <button onClick={() => setStage("practice")} className="btn-primary mt-4 w-full">开始答题</button>
      )}
    </div>
  );
}
