"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getUserId } from "@/lib/api";
import type { Course, ReviewItem } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

export default function ReviewNavPage() {
  const [course, setCourse] = useState<Course | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const list = await api<Course[]>(`/users/${getUserId()}/courses`);
        const saved = typeof window !== "undefined" ? localStorage.getItem("aiec_selected_course") : null;
        const c = list?.find((x) => x.id === saved) || list?.[0] || null;
        setCourse(c);
        if (c) {
          const r = await api<{ items: ReviewItem[] }>(`/courses/${c.id}/review`);
          setItems(r.items || []);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Loading />;

  if (!course) {
    return (
      <div className="px-4 pt-12">
        <EmptyState icon="🔁" title="还没有课程" hint="创建课程后即可查看需要强化的知识点" />
        <Link href="/course/new" className="btn-primary mt-4 block w-full text-center">
          创建课程
        </Link>
      </div>
    );
  }

  if (!items.length) {
    return <EmptyState icon="🎉" title="暂无需要强化的知识点" hint="继续保持，多做练习巩固掌握" />;
  }

  return (
    <div className="space-y-4 px-4 pt-6">
      <h1 className="text-xl font-extrabold">错题强化</h1>
      <p className="text-sm text-muted">《{course.name}》中有 {items.length} 个知识点需要巩固</p>
      {items.map((item) => {
        const accuracy = item.recent_accuracy ?? 0;
        return (
        <Link key={item.study_unit_id} href={`/learn/${item.study_unit_id}`} className="card block transition active:scale-[0.99]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-semibold">{item.title}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                <span className={item.importance_label === "HIGH" ? "chip chip-high" : "chip chip-low"}>
                  {item.importance_text}
                </span>
                <span>{item.estimated_minutes} 分钟</span>
              </div>
            </div>
            <div className={`shrink-0 text-lg font-extrabold ${accuracy >= 70 ? "text-primary" : "text-danger"}`}>
              {item.recent_accuracy == null ? "—" : `${Math.round(item.recent_accuracy)}%`}
            </div>
          </div>
        </Link>
        );
      })}
    </div>
  );
}
