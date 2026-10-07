"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardData } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";
import { ProgressPanel } from "@/components/Progress";

export default function CourseHomePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestInFlight = useRef(false);

  const loadDashboard = useCallback(async (showLoading = false) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    if (showLoading) setLoading(true);
    setError("");
    try {
      setData(await api<DashboardData>(`/courses/${id}/dashboard`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void loadDashboard(true);
  }, [loadDashboard]);

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void loadDashboard();
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [loadDashboard]);

  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="px-4 pt-16 text-center">
        <p className="text-danger">{error}</p>
        <Link href="/" className="btn-outline mt-4 inline-block">
          返回
        </Link>
      </div>
    );
  }
  if (!data) return null;

  const { course, progress, recommendation, action_batch, review_items, materials } = data;
  const examFocus = data.exam_focus || { real_exam_active_count: 64, practice_ready_count: 58, supplementary_count: 303 };
  const analyzing = course.status === "ANALYZING";
  const ready = course.status === "READY" || course.status === "LEARNING";
  const pendingMaterials = materials.filter((m) => m.status !== "COMPLETED").length;

  return (
    <div className="space-y-4 px-4 pt-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-extrabold">{course.name}</h1>
          {course.school && <p className="text-sm text-muted">{course.school}</p>}
        </div>
        <Link href={`/courses/${id}/settings`} className="text-xl text-muted" aria-label="设置">
          ⚙️
        </Link>
      </div>

      {course.days_remaining != null && (
        <div className="card flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">距离考试</div>
            <div className="text-3xl font-extrabold text-primary">{course.days_remaining}</div>
          </div>
          <div className="text-sm text-muted">
            {course.days_remaining <= 2
              ? "进入最后冲刺"
              : course.days_remaining <= 4
                ? "扩大覆盖范围"
                : "稳步强化"}
          </div>
        </div>
      )}

      <ProgressPanel progress={progress} />

      {analyzing && (
        <div className="card">
          <Loading text={pendingMaterials ? `AI 正在解析资料（剩余 ${pendingMaterials} 份）…` : "AI 正在解析资料…"} />
          <Link href={`/courses/${id}/preparing`} className="btn-outline mt-2 block w-full text-center">
            查看资料
          </Link>
        </div>
      )}

      {ready && recommendation && (
        <div className="card border-2 border-primary/40">
          <div className="mb-1 text-xs font-bold uppercase tracking-wide text-primary">今日推荐</div>
          <div className="text-lg font-bold text-slate-800">{recommendation.study_unit.title}</div>
          <p className="mt-1 text-sm text-muted">{recommendation.reason.text}</p>
          {recommendation.study_unit.exam_evidence_summary?.text && (
            <p className="mt-2 text-xs font-semibold text-secondary">{recommendation.study_unit.exam_evidence_summary.text}</p>
          )}
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className={`chip ${recommendation.study_unit.exam_evidence_tier === "REAL_EXAM_ACTIVE" ? "chip-high" : "chip-low"}`}>
              {recommendation.study_unit.exam_evidence_tier === "REAL_EXAM_ACTIVE" ? "真题重点" : "图谱知识"}
            </span>
            <span className="text-muted">预计 {recommendation.estimated_minutes} 分钟</span>
          </div>
          <Link href={`/learn/${recommendation.study_unit.id}`} className="btn-primary mt-4 block w-full text-center">
            开始学习
          </Link>
        </div>
      )}

      {ready && action_batch && action_batch.items.length > 0 && (
        <div className="card border-2 border-primary/20">
          <div className="text-lg font-bold text-slate-800">{action_batch.title}</div>
          <p className="mt-1 text-sm text-muted">{action_batch.reason}</p>
          <div className="mt-3 space-y-2">
            {action_batch.items.map((item) => (
              <Link key={item.id} href={`/learn/${item.id}`} className="flex items-center justify-between rounded-lg bg-bg px-3 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{item.title}</div>
                  {item.exam_evidence_summary?.text && <div className="mt-1 text-xs text-muted">{item.exam_evidence_summary.text}</div>}
                </div>
                <span className="ml-3 shrink-0 text-xs text-secondary">{item.estimated_minutes} 分钟 →</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {ready && (
        <div className="card border-2 border-secondary/30">
          <div className="text-sm font-bold text-secondary">先抓真题重点，再补完整知识图谱</div>
          <div className="mt-2 flex items-end gap-4">
            <div><div className="text-2xl font-extrabold">{examFocus.real_exam_active_count}</div><div className="text-xs text-muted">真题重点</div></div>
            <div><div className="text-2xl font-extrabold">{examFocus.practice_ready_count}</div><div className="text-xs text-muted">可直接练真题</div></div>
            <div><div className="text-2xl font-extrabold">{examFocus.supplementary_count}</div><div className="text-xs text-muted">补充知识</div></div>
          </div>
          <Link href={`/courses/${id}/ranking?focus=exam`} className="btn-secondary mt-3 block w-full text-center">
            进入真题重点
          </Link>
        </div>
      )}

      {ready && review_items.length > 0 && (
        <div className="card">
          <div className="mb-2 text-sm font-bold">知识点强化（{review_items.length}）</div>
          <div className="space-y-2">
            {review_items.slice(0, 3).map((item) => (
              <Link
                key={item.study_unit_id}
                href={`/learn/${item.study_unit_id}`}
                className="flex items-center justify-between rounded-lg bg-bg px-3 py-2"
              >
                <span className="truncate text-sm">{item.title}</span>
                <span className="ml-2 shrink-0 text-xs text-muted">
                  准确率 {item.recent_accuracy == null ? "—" : `${Math.round(item.recent_accuracy)}%`}
                </span>
              </Link>
            ))}
          </div>
          {review_items.length > 3 && (
            <Link href={`/courses/${id}/review`} className="mt-2 block text-center text-sm font-semibold text-secondary">
              查看全部
            </Link>
          )}
        </div>
      )}

      {ready && (
        <div className="grid grid-cols-2 gap-3">
          <Link href={`/courses/${id}/ranking`} className="card block text-center">
            <div className="text-2xl">📊</div>
            <div className="mt-1 font-bold">知识点排名</div>
          </Link>
          <Link href={`/courses/${id}/knowledge`} className="card block text-center">
            <div className="text-2xl">🗂️</div>
            <div className="mt-1 font-bold">知识图谱</div>
          </Link>
          <Link href={`/courses/${id}/review`} className="card block text-center">
            <div className="text-2xl">🔁</div>
            <div className="mt-1 font-bold">错题强化</div>
          </Link>
          <Link href={`/courses/${id}/wrong-book`} className="card block text-center">
            <div className="text-2xl">📕</div>
            <div className="mt-1 font-bold">错题本</div>
          </Link>
        </div>
      )}

      {!analyzing && !ready && (
        <EmptyState icon="📂" title="课程尚未就绪" hint="请先在资料页上传学习资料" />
      )}
      {!analyzing && course.status === "CREATED" && (
        <Link href={`/courses/${id}/preparing`} className="btn-primary block w-full text-center">
          去上传资料
        </Link>
      )}

      {materials.length > 0 && (
        <Link href={`/courses/${id}/preparing`} className="block pt-1 text-center text-sm text-muted">
          管理资料（{materials.length} 份）
        </Link>
      )}
    </div>
  );
}
