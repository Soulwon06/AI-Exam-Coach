"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { KnowledgeData, StudyUnitNode } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

const masteryMap: Record<string, { label: string; cls: string }> = {
  MASTERED: { label: "已掌握", cls: "chip-green" },
  REVIEW: { label: "需复习", cls: "chip-red" },
  WEAK: { label: "薄弱", cls: "chip-red" },
  LEARNING: { label: "学习中", cls: "chip-medium" },
  SKIPPED: { label: "已跳过", cls: "chip-low" },
  UNKNOWN: { label: "未开始", cls: "chip-low" },
};

export default function KnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<KnowledgeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setData(await api<KnowledgeData>(`/courses/${id}/knowledge`));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <Loading />;
  if (!data) return null;

  const total = data.total ?? data.domains.reduce((n, d) => n + (d.sections ? d.sections.reduce((m, s) => m + s.children.length, 0) : d.children.length), 0);
  if (!total) return <EmptyState icon="🗂️" title="暂无知识点" hint="上传资料并等待 AI 解析后可见" />;

  return (
    <div className="space-y-4 px-4 pt-6">
      <h1 className="text-xl font-extrabold">知识图谱</h1>
      <p className="text-sm text-muted">共 {total} 个知识点，点击可进入学习</p>

      {data.domains.map((domain) => (
        <div key={domain.id} className="card">
          <div className="mb-2 font-bold text-slate-800">{domain.title}</div>
          <div className="space-y-3">
            {(domain.sections ?? [{ id: domain.id, title: "知识点", children: domain.children }]).map((section) => <div key={section.id}>
              {domain.sections && <div className="mb-1 text-xs font-semibold text-muted">{section.title}</div>}
              <div className="space-y-1.5">
            {section.children.map((u: StudyUnitNode) => {
              const m = masteryMap[u.mastery_status] || masteryMap.UNKNOWN;
              return (
                <Link
                  key={u.id}
                  href={`/learn/${u.id}`}
                  className="flex items-center justify-between gap-2 rounded-xl bg-bg px-3 py-2.5 transition active:scale-[0.99]"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{u.title}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                      <span className={u.exam_evidence_tier === "REAL_EXAM_ACTIVE" ? "chip chip-high" : "chip chip-low"}>
                        {u.exam_evidence_tier === "REAL_EXAM_ACTIVE" ? "真题重点" : "图谱知识"}
                      </span>
                      {u.practice_question_binding_ready && <span className="text-primary">可练真题</span>}
                      <span>{u.estimated_minutes} 分钟</span>
                    </div>
                  </div>
                  <span className={`chip shrink-0 ${m.cls}`}>{m.label}</span>
                </Link>
              );
            })}
              </div>
            </div>)}
          </div>
        </div>
      ))}
    </div>
  );
}
