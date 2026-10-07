"use client";

import React from "react";
import { availabilityText, canStartPractice } from "@/lib/d5g-contract.mjs";
import type { RankingData, RankingItem } from "@/lib/types";
import { priorityLabel, relativePriorityLabel, studentStatusLabel } from "@/lib/student-copy";
import Loading, { EmptyState } from "@/components/State";

interface RankingResultsProps {
  data: RankingData | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
  startingId: string | null;
  onStart: (item: RankingItem) => void;
}

function itemTitle(item: RankingItem): string {
  return item.title || item.name_cn || item.name_en || item.canonical_kp_id;
}

export default function RankingResults({ data, loading, error, onRetry, startingId, onStart }: RankingResultsProps) {
  if (loading && !data) return <Loading text="正在加载真实知识点排名…" />;
  if (error && !data) {
    return (
      <div className="px-4 pt-16 text-center">
        <p className="text-danger">{error}</p>
        <button onClick={onRetry} className="btn-primary mt-4">重新加载</button>
      </div>
    );
  }
  if (!data || data.items.length === 0) {
    return <EmptyState icon="📊" title="暂无可展示的知识点排名" hint="请确认课程资料已完成解析" />;
  }

  return (
    <div className="space-y-3">
      {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      {data.items.map((item) => {
        const ready = canStartPractice(item);
        const progress = item.progress == null ? null : Math.round(item.progress);
        return (
          <div key={item.canonical_kp_id} className="card">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 font-extrabold text-primary">
                {item.ranking_position}
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-bold text-slate-800">{itemTitle(item)}</div>
                <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted">
                  <span>{relativePriorityLabel(item.display_priority_score ?? item.ranking_score)}</span>
                  {item.exam_evidence_tier && <span className="chip chip-high">{priorityLabel(item)}</span>}
                  {item.mastery_status && <span className="chip chip-low">{studentStatusLabel(item.mastery_status)}</span>}
                  {progress != null && <span>进度 {progress}%</span>}
                </div>
              </div>
            </div>
            <div className={`mt-3 rounded-xl px-3 py-2 text-sm ${ready ? "bg-emerald-50 text-emerald-700" : "bg-slate-50 text-slate-600"}`}>
              {availabilityText(item.practice_binding_status)}
            </div>
            {ready ? (
              <button
                onClick={() => onStart(item)}
                disabled={startingId !== null}
                className="btn-primary mt-3 w-full disabled:opacity-50"
              >
                {startingId === item.study_unit_id ? "准备练习…" : "开始练习"}
              </button>
            ) : item.study_unit_id ? (
              <a
                href={`/learn/${item.study_unit_id}`}
                className="btn-secondary mt-3 block w-full text-center"
              >
                学习知识点
              </a>
            ) : (
              <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-center text-sm text-muted">暂无可练真题</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
