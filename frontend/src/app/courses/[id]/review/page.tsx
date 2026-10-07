"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ReviewItem } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ items: ReviewItem[] }>(`/courses/${id}/review`);
        setItems(r.items || []);
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <Loading />;

  if (!items.length) {
    return <EmptyState icon="🎉" title="暂无需要强化的知识点" hint="继续保持，多做练习巩固掌握" />;
  }

  return (
    <div className="space-y-4 px-4 pt-6">
      <h1 className="text-xl font-extrabold">错题强化</h1>
      <p className="text-sm text-muted">以下知识点需要重新巩固</p>

      {items.map((item) => {
        const accuracy = item.recent_accuracy ?? 0;
        return (
        <Link key={item.study_unit_id} href={`/learn/${item.study_unit_id}`} className="card block transition active:scale-[0.99]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold">{item.title}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                <span className={item.importance_label === "HIGH" ? "chip chip-high" : "chip chip-low"}>
                  重要性：{item.importance_text}
                </span>
                <span>{item.estimated_minutes} 分钟</span>
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-xs text-muted">近期准确率</div>
              <div className={`text-lg font-extrabold ${accuracy >= 70 ? "text-primary" : "text-danger"}`}>
                {item.recent_accuracy == null ? "—" : `${Math.round(item.recent_accuracy)}%`}
              </div>
            </div>
          </div>
        </Link>
        );
      })}
    </div>
  );
}
