"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Course } from "@/lib/types";
import Loading from "@/components/State";

export default function SettingsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [examDate, setExamDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingDate, setSavingDate] = useState(false);
  const [dateMessage, setDateMessage] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const currentCourse = await api<Course>(`/courses/${id}`);
        setCourse(currentCourse);
        setExamDate(currentCourse.exam_date || "");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) return <Loading />;
  if (!course) return null;

  const archive = async () => {
    if (!confirm("确定归档该课程？")) return;
    try {
      await api(`/courses/${id}/archive`, { method: "POST" });
      router.push("/");
    } catch (e) {
      alert(e instanceof Error ? e.message : "操作失败");
    }
  };

  const saveExamDate = async () => {
    setSavingDate(true);
    setDateMessage("");
    try {
      const updated = await api<Course>(`/courses/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ exam_date: examDate || null }),
      });
      setCourse(updated);
      setExamDate(updated.exam_date || "");
      setDateMessage("考试日期已保存");
    } catch (e) {
      setDateMessage(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSavingDate(false);
    }
  };

  return (
    <div className="space-y-4 px-4 pt-6">
      <h1 className="text-xl font-extrabold">课程设置</h1>

      <div className="card space-y-3">
        <div className="flex justify-between">
          <span className="text-sm text-muted">课程</span>
          <span className="font-semibold">{course.name}</span>
        </div>
        {course.school && (
          <div className="flex justify-between">
            <span className="text-sm text-muted">学校</span>
            <span>{course.school}</span>
          </div>
        )}
        <label className="block">
          <span className="text-sm text-muted">考试日期</span>
          <div className="mt-1 flex gap-2">
            <input
              type="date"
              value={examDate}
              onChange={(event) => setExamDate(event.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2"
            />
            <button
              type="button"
              onClick={saveExamDate}
              disabled={savingDate}
              className="btn-secondary px-4 py-2"
            >
              {savingDate ? "保存中…" : "保存"}
            </button>
          </div>
          {dateMessage && <p className="mt-2 text-sm text-muted">{dateMessage}</p>}
        </label>
      </div>

      <div className="space-y-2">
        <Link href={`/courses/${id}/preparing`} className="btn-outline block w-full text-center">
          管理学习资料
        </Link>
        <Link href={`/courses/${id}/knowledge`} className="btn-outline block w-full text-center">
          知识图谱
        </Link>
        <Link href={`/courses/${id}/review`} className="btn-outline block w-full text-center">
          错题强化
        </Link>
      </div>

      <button onClick={archive} className="btn-danger w-full">
        归档课程
      </button>
    </div>
  );
}
