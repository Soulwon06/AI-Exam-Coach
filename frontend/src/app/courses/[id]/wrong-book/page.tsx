"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, retryWrongQuestion, userSafeError } from "@/lib/api";
import type { WrongBookItem } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

export default function WrongBookPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [items, setItems] = useState<WrongBookItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { (async () => { try { const data = await api<{ items: WrongBookItem[] }>(`/courses/${id}/wrong-book`); setItems(data.items || []); } finally { setLoading(false); } })(); }, [id]);
  if (loading) return <Loading />;
  if (!items.length) return <EmptyState icon="🎉" title="暂无未解决错题" hint="完成练习后，未答对且尚未纠正的题目会出现在这里" />;
  return <div className="space-y-4 px-4 pt-6">
    <div><h1 className="text-xl font-extrabold">错题本</h1><p className="text-sm text-muted">按题目记录，和知识点强化分开</p></div>
    {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
    {items.map((item) => <div key={`${item.question_id}-${item.study_unit_id}`} className="card">
      <div className="text-xs text-muted">{item.knowledge_point_title}{item.exam_year ? ` · ${item.exam_year}` : ""}</div>
      <div className="mt-2 font-semibold">{item.content}</div>
      {item.previous_answer && <div className="mt-3 text-sm"><span className="text-muted">上一次答案：</span>{item.previous_answer}</div>}
      <div className="mt-3 text-sm"><span className="text-muted">你的答案：</span>{item.latest_answer || "—"}</div>
      <div className="mt-1 text-sm"><span className="text-muted">正确答案：</span>{item.correct_answer}</div>
      {item.explanation && <div className="mt-3 rounded-lg bg-bg p-3 text-sm">{item.explanation}</div>}
      {(item.source_material || item.exam_year || item.question_number) && <div className="mt-3 text-xs text-muted">来源：{item.source_material || "课程真题"}{item.exam_year ? ` · ${item.exam_year} 年` : ""}{item.question_number ? ` · 第 ${item.question_number} 题` : ""}</div>}
      <button
        className="btn-primary mt-3 block w-full"
        disabled={retrying !== null}
        onClick={async () => {
          setRetrying(item.question_id);
          setError("");
          try {
            const session = await retryWrongQuestion(id, item.question_id, item.study_unit_id);
            router.push(`/learning-sessions/${session.session_id}`);
          } catch (requestError) {
            setError(userSafeError(requestError, "错题暂时无法重做"));
            setRetrying(null);
          }
        }}
      >
        {retrying === item.question_id ? "准备原题…" : "重做这道原题"}
      </button>
      <Link href={`/learn/${item.study_unit_id}`} className="btn-outline mt-2 block w-full text-center">进入知识点强化</Link>
    </div>)}
  </div>;
}
