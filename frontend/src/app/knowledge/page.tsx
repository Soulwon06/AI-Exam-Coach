"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getUserId } from "@/lib/api";
import type { Course } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

export default function KnowledgeNavPage() {
  const [course, setCourse] = useState<Course | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const list = await api<Course[]>(`/users/${getUserId()}/courses`);
        setCourses(list || []);
        const saved = typeof window !== "undefined" ? localStorage.getItem("aiec_selected_course") : null;
        setCourse(list?.find((c) => c.id === saved) || list?.[0] || null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Loading />;

  if (!course) {
    return (
      <div className="px-4 pt-12">
        <EmptyState icon="🗂️" title="还没有课程" hint="创建课程并上传资料后即可查看知识图谱" />
        <Link href="/course/new" className="btn-primary mt-4 block w-full text-center">
          创建课程
        </Link>
      </div>
    );
  }

  return (
    <div className="px-4 pt-6">
      {courses.length > 1 && (
        <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
          {courses.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                setCourse(c);
                if (typeof window !== "undefined") localStorage.setItem("aiec_selected_course", c.id);
              }}
              className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold ${
                course.id === c.id ? "bg-primary text-white" : "bg-white text-muted"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}
      <Link href={`/courses/${course.id}/knowledge`} className="card block">
        <div className="text-3xl">🗂️</div>
        <div className="mt-1 font-bold text-slate-800">查看《{course.name}》知识图谱</div>
        <div className="mt-0.5 text-sm text-muted">知识点 → 重要程度 → 掌握状态</div>
      </Link>
    </div>
  );
}
