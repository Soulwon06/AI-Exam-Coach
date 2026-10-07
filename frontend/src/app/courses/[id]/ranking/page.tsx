"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getCourseRanking, startQuestionFirstSession, userSafeError } from "@/lib/api";
import { canStartPractice } from "@/lib/d5g-contract.mjs";
import type { RankingData, RankingItem } from "@/lib/types";
import RankingResults from "@/components/RankingResults";

export default function RankingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [focus, setFocus] = useState<"all" | "exam">(searchParams.get("focus") === "exam" ? "exam" : "all");
  const [data, setData] = useState<RankingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [startingId, setStartingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const request = focus === "exam"
        ? getCourseRanking(id, { examEvidenceTier: "REAL_EXAM_ACTIVE" })
        : getCourseRanking(id);
      setData(await request);
    } catch (e) {
      setError(userSafeError(e, "排名加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id, focus]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [load]);

  async function start(item: RankingItem) {
    if (!item.study_unit_id || !canStartPractice(item) || startingId) return;
    setStartingId(item.study_unit_id);
    setError("");
    try {
      const session = await startQuestionFirstSession(item.study_unit_id);
      router.push(`/learning-sessions/${session.session_id}`);
    } catch (e) {
      setError(userSafeError(e, "练习启动失败"));
      setStartingId(null);
    }
  }

  return (
    <div className="space-y-4 px-4 pb-6 pt-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">知识点排名</h1>
          <p className="mt-1 text-sm text-muted">按后端已验证的考试相关性排序，共 {data?.filtered_total ?? 0} 个知识点</p>
        </div>
        <Link href={`/courses/${id}`} className="text-sm font-semibold text-secondary">返回课程</Link>
      </div>

      <div className="card flex gap-2 p-2" role="tablist" aria-label="知识点范围">
        <button
          role="tab"
          aria-selected={focus === "exam"}
          onClick={() => setFocus("exam")}
          className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold ${focus === "exam" ? "bg-primary text-white" : "bg-bg text-muted"}`}
        >
          真题重点（64）
        </button>
        <button
          role="tab"
          aria-selected={focus === "all"}
          onClick={() => setFocus("all")}
          className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold ${focus === "all" ? "bg-primary text-white" : "bg-bg text-muted"}`}
        >
          全部知识（367）
        </button>
      </div>
      <p className="text-xs text-muted">真题重点优先用于考前复习；其余知识点用于补充完整知识图谱，不代表没有学习价值。</p>

      <RankingResults
        data={data}
        loading={loading}
        error={error}
        onRetry={() => void load()}
        startingId={startingId}
        onStart={(item) => void start(item)}
      />
    </div>
  );
}
