"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getUserId } from "@/lib/api";
import type { Course } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

const USER_ID_KEY = "aiec_selected_course";

function currentCourseId(): string | null {
  return typeof window !== "undefined" ? localStorage.getItem(USER_ID_KEY) : null;
}

export default function HomePage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const list = await api<Course[]>(`/users/${getUserId()}/courses`);
        setCourses(list || []);
        const saved = currentCourseId();
        setSelected(saved && list?.some((c) => c.id === saved) ? saved : list?.[0]?.id ?? null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Loading />;

  if (!courses.length) {
    return (
      <div className="px-4 pt-8">
        <EmptyState icon="🎯" title="还没有课程" hint="上传你的备考资料，AI 帮你拆解考点并制定学习计划" />
        <Link href="/course/new" className="btn-primary mt-6 block w-full">
          创建课程
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3 px-4 pt-6">
      <h1 className="text-xl font-extrabold">我的课程</h1>
      {courses.map((c) => (
        <Link
          key={c.id}
          href={`/courses/${c.id}`}
          onClick={() => {
            if (typeof window !== "undefined") localStorage.setItem(USER_ID_KEY, c.id);
            setSelected(c.id);
          }}
          className="card block transition active:scale-[0.99]"
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="text-lg font-bold text-slate-800">{c.name}</div>
              {c.exam_date && (
                <div className="mt-0.5 text-sm text-muted">
                  {c.days_remaining != null && c.days_remaining > 0
                    ? `距考试 ${c.days_remaining} 天`
                    : "考试日期"}
                </div>
              )}
            </div>
            <span
              className={              `chip ${
                c.status === "READY" || c.status === "LEARNING"
                  ? "chip-green"
                  : c.status === "ANALYZING"
                    ? "chip-medium"
                    : "chip-low"
              }`}
            >
              {c.status === "CREATED"
                ? "待处理"
                : c.status === "ANALYZING"
                  ? "处理中"
                  : c.status === "READY"
                    ? "可学习"
                    : c.status === "LEARNING"
                      ? "学习中"
                      : c.status === "ARCHIVED"
                        ? "已归档"
                        : "失败"}
            </span>
          </div>
          {c.progress && (
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${Math.min(100, c.progress.mastery)}%` }}
              />
            </div>
          )}
        </Link>
      ))}
      <Link href="/course/new" className="btn-outline mt-2 block w-full">
        + 新建课程
      </Link>
    </div>
  );
}
