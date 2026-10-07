"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

const MODES = [
  { value: "EXPLANATION_FIRST", label: "先讲后练", hint: "先看知识点讲解，再做题巩固" },
  { value: "QUESTION_FIRST", label: "先练后讲", hint: "先做题检验，再看讲解查漏" },
];

export default function CourseNewPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [examDate, setExamDate] = useState("");
  const [school, setSchool] = useState("");
  const [teacher, setTeacher] = useState("");
  const [mode, setMode] = useState("EXPLANATION_FIRST");
  const [simulate, setSimulate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function create() {
    if (!name.trim()) {
      setError("请填写课程名称");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const course = await api<{ id: string }>("/courses", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          exam_date: examDate || null,
          school: school.trim() || null,
          teacher: teacher.trim() || null,
          preferences: {
            learning_mode: mode,
            simulation: simulate,
          },
        }),
      });
      if (typeof window !== "undefined") localStorage.setItem("aiec_selected_course", course.id);
      router.push(`/courses/${course.id}/preparing`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5 px-4 pt-8">
      <div className="text-center">
        <div className="text-4xl">📚</div>
        <h1 className="mt-2 text-2xl font-extrabold">创建课程</h1>
        <p className="mt-1 text-sm text-muted">上传备考资料，AI 将拆解考点并制定学习计划</p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="mb-1 block text-sm font-semibold">课程名称 *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：计算机网络"
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-primary"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-semibold">考试日期</label>
          <input
            type="date"
            value={examDate}
            onChange={(e) => setExamDate(e.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-primary"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-sm font-semibold">学校</label>
            <input
              value={school}
              onChange={(e) => setSchool(e.target.value)}
              className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-semibold">老师</label>
            <input
              value={teacher}
              onChange={(e) => setTeacher(e.target.value)}
              className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-primary"
            />
          </div>
        </div>
      </div>

      <div className="card space-y-3">
        <label className="text-sm font-semibold">学习方式</label>
        <div className="space-y-2">
          {MODES.map((m) => (
            <button
              key={m.value}
              onClick={() => setMode(m.value)}
              className={`flex w-full items-center gap-3 rounded-xl border-2 p-3 text-left transition ${
                mode === m.value ? "border-primary bg-primary/5" : "border-slate-200"
              }`}
            >
              <div className="flex-1">
                <div className="font-bold">{m.label}</div>
                <div className="text-xs text-muted">{m.hint}</div>
              </div>
              <span
                className={`h-5 w-5 rounded-full border-2 ${
                  mode === m.value ? "border-primary bg-primary" : "border-slate-300"
                }`}
              />
            </button>
          ))}
        </div>
      </div>

      <label className="card flex cursor-pointer items-center justify-between">
        <div>
          <div className="font-semibold">真题模拟</div>
          <div className="text-xs text-muted">冲刺阶段按真实考试形式出题</div>
        </div>
        <input
          type="checkbox"
          checked={simulate}
          onChange={(e) => setSimulate(e.target.checked)}
          className="h-5 w-5 accent-primary"
        />
      </label>

      {error && <p className="text-center text-sm text-danger">{error}</p>}

      <button onClick={create} disabled={submitting} className="btn-primary w-full disabled:opacity-50">
        {submitting ? "创建中…" : "创建课程"}
      </button>
    </div>
  );
}
