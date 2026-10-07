"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getUserId, setAuthenticatedUserId } from "@/lib/api";
import type { Course } from "@/lib/types";
import Loading from "@/components/State";

export default function MePage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setCourses((await api<Course[]>(`/users/${getUserId()}/courses`)) || []);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Loading />;

  const active = courses.filter((c) => c.status !== "ARCHIVED");
  const mastered = active.reduce((sum, c) => sum + (c.progress?.mastery || 0), 0);
  const avg = active.length ? Math.round(mastered / active.length) : 0;

  return (
    <div className="space-y-4 px-4 pt-6">
      <div className="card text-center">
        <div className="text-5xl">👤</div>
        <div className="mt-2 text-lg font-extrabold">我的学习</div>
        <div className="mt-1 text-xs text-muted">用户 ID：{getUserId().slice(0, 8)}…</div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="card text-center">
          <div className="text-2xl font-extrabold text-primary">{active.length}</div>
          <div className="text-xs text-muted">进行中课程</div>
        </div>
        <div className="card text-center">
          <div className="text-2xl font-extrabold text-secondary">{avg}%</div>
          <div className="text-xs text-muted">平均掌握度</div>
        </div>
      </div>

      {active.length > 0 && (
        <div className="card space-y-2">
          <div className="text-sm font-bold">我的课程</div>
          {active.map((c) => (
            <Link key={c.id} href={`/courses/${c.id}`} className="flex items-center justify-between rounded-lg bg-bg px-3 py-2">
              <span className="truncate text-sm font-medium">{c.name}</span>
              <span className="text-xs text-muted">掌握 {Math.round(c.progress?.mastery || 0)}%</span>
            </Link>
          ))}
        </div>
      )}

      <Link href="/course/new" className="btn-outline block w-full text-center">
        + 新建课程
      </Link>
      <button
        type="button"
        className="btn-outline block w-full"
        onClick={async () => {
          try {
            await api<{ logged_out: boolean }>("/auth/logout", { method: "POST", body: "{}" });
          } finally {
            setAuthenticatedUserId(null);
            window.location.assign("/login");
          }
        }}
      >
        退出登录
      </button>
    </div>
  );
}
