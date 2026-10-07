"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "@/lib/api";
import type { Course, CourseReadiness, Material } from "@/lib/types";
import Loading, { EmptyState } from "@/components/State";

type PendingUpload = {
  id: string;
  file: File;
  type: string;
  status: "PENDING" | "UPLOADING" | "UPLOADED" | "FAILED";
  error?: string;
};

const MAX_PARALLEL_UPLOADS = 2;

export default function PreparingPage() {
  const { id } = useParams<{ id: string }>();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [course, setCourse] = useState<Course | null>(null);
  const [readiness, setReadiness] = useState<CourseReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<PendingUpload[]>([]);
  const uploadQueueRef = useRef<PendingUpload[]>([]);
  const [uploadingUrl, setUploadingUrl] = useState(false);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [maxUploadMb, setMaxUploadMb] = useState(100);
  const [materialType, setMaterialType] = useState("TEXTBOOK");
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);

  const TYPE_OPTIONS: { value: string; label: string; icon: string }[] = [
    { value: "TEXTBOOK", label: "教材讲义", icon: "📚" },
    { value: "REAL_EXAM", label: "历年真题", icon: "📝" },
    { value: "TEACHER_PPT", label: "老师课件", icon: "🖥️" },
    { value: "CLASS_NOTES", label: "课堂笔记", icon: "🗒️" },
    { value: "HOMEWORK", label: "课后作业", icon: "✏️" },
    { value: "OTHER", label: "其他资料", icon: "📁" },
  ];

  async function refresh() {
    try {
      const dash = await api<{ course: Course; materials: Material[]; readiness?: CourseReadiness }>(`/courses/${id}/dashboard`);
      setMaterials(dash.materials || []);
      setCourse(dash.course || null);
      setReadiness(dash.readiness || null);
      return dash;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    api<{ maxUploadMb?: number }>("/health").then((h) => {
      if (typeof h?.maxUploadMb === "number" && h.maxUploadMb > 0) setMaxUploadMb(h.maxUploadMb);
    });
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [id]);

  const processing = materials.some((m) => m.status === "PENDING" || m.status === "PROCESSING");
  const courseReady = Boolean(
    readiness?.ready && course && (course.status === "READY" || course.status === "LEARNING"),
  );

  const ALLOWED = [".txt", ".md", ".pdf", ".ppt", ".pptx", ".doc", ".docx"];

  function localCheck(file: File): string | null {
    const name = file.name.toLowerCase();
    const ext = "." + name.split(".").pop();
    if (!ALLOWED.includes(ext)) return `「${file.name}」类型不支持（支持 ${ALLOWED.join(" / ")}）`;
    if (file.size > maxUploadMb * 1024 * 1024) return `「${file.name}」超过 ${maxUploadMb}MB 上限（超大 PDF 建议拆成章节再传）`;
    return null;
  }

  function replaceUploadQueue(next: PendingUpload[] | ((previous: PendingUpload[]) => PendingUpload[])) {
    setUploadQueue((previous) => {
      const value = typeof next === "function" ? next(previous) : next;
      uploadQueueRef.current = value;
      return value;
    });
  }

  function updateUpload(id: string, patch: Partial<PendingUpload>) {
    replaceUploadQueue((previous) => previous.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  async function onFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setError("");
    const accepted: PendingUpload[] = [];
    const failures: string[] = [];
    files.forEach((file) => {
      const pre = localCheck(file);
      if (pre) failures.push(pre);
      else accepted.push({ id: `${file.name}-${file.lastModified}-${Math.random()}`, file, type: materialType, status: "PENDING" });
    });
    if (accepted.length) replaceUploadQueue((previous) => [...previous, ...accepted]);
    if (failures.length) setError(failures.join("；"));
    if (fileRef.current) fileRef.current.value = "";
    if (dirRef.current) dirRef.current.value = "";
  }

  async function startUploadQueue() {
    const pendingIds = uploadQueueRef.current.filter((item) => item.status === "PENDING").map((item) => item.id);
    if (!pendingIds.length || uploading) return;
    setUploading(true);
    setError("");
    let cursor = 0;
    const worker = async () => {
      while (cursor < pendingIds.length) {
        const uploadId = pendingIds[cursor++];
        const item = uploadQueueRef.current.find((candidate) => candidate.id === uploadId);
        if (!item) continue;
        updateUpload(uploadId, { status: "UPLOADING", error: undefined });
        try {
          const form = new FormData();
          form.append("file", item.file);
          form.append("type", item.type);
          const res = await fetch(apiUrl(`/courses/${id}/materials`), {
            method: "POST",
            credentials: "include",
            body: form,
          });
          const body = await res.json().catch(() => null);
          if (!res.ok || body?.error) throw new Error(body?.error?.message || "上传失败");
          updateUpload(uploadId, { status: "UPLOADED" });
        } catch (err) {
          // A response can be lost after the backend has already persisted the
          // Material. Refresh once before showing a real failure to the user.
          const dash = await refresh().catch(() => null);
          const persisted = dash?.materials?.some((material) => material.name === item.file.name);
          updateUpload(uploadId, {
            status: persisted ? "UPLOADED" : "FAILED",
            error: persisted ? "已上传，正在确认处理状态" : (err instanceof Error ? err.message : "上传失败"),
          });
        }
      }
    };
    try {
      await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL_UPLOADS, pendingIds.length) }, worker));
      await refresh();
    } finally {
      setUploading(false);
    }
  }

  function removePendingUpload(id: string) {
    if (uploadQueueRef.current.find((item) => item.id === id)?.status !== "PENDING") return;
    replaceUploadQueue((previous) => previous.filter((item) => item.id !== id));
  }

  function changePendingType(id: string, type: string) {
    updateUpload(id, { type });
  }

  async function uploadByUrl() {
    if (!url.trim()) return;
    setUploadingUrl(true);
    setError("");
    try {
      await api(`/courses/${id}/materials/url`, {
        method: "POST",
        body: JSON.stringify({ url: url.trim(), type: materialType }),
      });
      setUrl("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "添加失败");
    } finally {
      setUploadingUrl(false);
    }
  }

  async function updateMaterialType(material: Material, type: string) {
    if (material.type === type) return;
    setError("");
    try {
      await api(`/courses/${id}/materials/${material.id}`, {
        method: "PATCH",
        body: JSON.stringify({ type }),
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "资料类型更新失败");
    }
  }

  async function removeMaterial(materialId: string, name: string) {
    if (!window.confirm(`确定删除资料「${name}」？\n相关知识点会重新计算。`)) return;
    setDeletingId(materialId);
    setError("");
    try {
      await api(`/courses/${id}/materials/${materialId}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId("");
    }
  }

  if (loading) return <Loading />;

  const statusText = (s: string) =>
    s === "COMPLETED" ? "已处理" : s === "PENDING" ? "排队中" : s === "PROCESSING" ? "解析中" : "失败";

  return (
    <div className="space-y-4 px-4 pt-8">
      <div className="text-center">
        <div className="text-4xl">⚙️</div>
        <h1 className="mt-2 text-2xl font-extrabold">准备课程资料</h1>
        <p className="mt-1 text-sm text-muted">上传讲义 / 教材 / 真题，AI 自动拆解考点</p>
      </div>

      <div className="card">
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => fileRef.current?.click()} className="btn-primary w-full">
              📄 添加文件
            </button>
            <button onClick={() => dirRef.current?.click()} className="btn-outline w-full">
              📁 添加文件夹
            </button>
          </div>
          <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.doc,.docx" multiple onChange={onFiles} className="hidden" />
          <input
            ref={(el) => {
              dirRef.current = el;
              if (el) el.setAttribute("webkitdirectory", "true");
            }}
            type="file"
            onChange={onFiles}
            className="hidden"
          />
          <div className="flex flex-wrap gap-1.5 pt-1">
            {TYPE_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => setMaterialType(o.value)}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  materialType === o.value
                    ? "bg-primary font-semibold text-white"
                    : "bg-bg text-muted hover:bg-slate-200"
                }`}
              >
                {o.icon} {o.label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="或粘贴资料链接"
              className="flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-primary"
            />
            <button onClick={uploadByUrl} disabled={uploadingUrl} className="btn-secondary px-4 disabled:opacity-50">
              {uploadingUrl ? "…" : "添加"}
            </button>
          </div>
          {uploadQueue.length > 0 && (
            <div className="space-y-2 rounded-xl bg-bg p-3">
              <div className="flex items-center justify-between text-sm font-semibold">
                <span>待上传文件（{uploadQueue.length}）</span>
                <button onClick={startUploadQueue} disabled={uploading || !uploadQueue.some((item) => item.status === "PENDING")} className="btn-primary px-3 py-1 text-xs disabled:opacity-50">
                  {uploading ? "上传中…" : "开始上传"}
                </button>
              </div>
              {uploadQueue.map((item) => (
                <div key={item.id} className="flex items-center gap-2 text-xs">
                  <span className="min-w-0 flex-1 truncate">{item.file.name}</span>
                  <select value={item.type} onChange={(e) => changePendingType(item.id, e.target.value)} disabled={item.status !== "PENDING"} className="rounded border border-slate-300 bg-white px-1 py-1">
                    {TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <span className="w-16 text-center text-muted">{item.status === "PENDING" ? "待上传" : item.status === "UPLOADING" ? "上传中" : item.status === "UPLOADED" ? "已接收" : "失败"}</span>
                  {item.status === "PENDING" && <button onClick={() => removePendingUpload(item.id)} className="text-danger" aria-label={`移除 ${item.file.name}`}>移除</button>}
                  {item.error && <span className="text-danger">{item.error}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {error && <p className="text-center text-sm text-danger">{error}</p>}

      {materials.length > 0 && (
        <div className="card space-y-2">
          <div className="text-sm font-semibold">已上传资料（{materials.length}）</div>
          {materials.map((m) => (
            <div key={m.id} className="flex items-center justify-between rounded-lg bg-bg px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <select value={m.type} onChange={(e) => updateMaterialType(m, e.target.value)} className="shrink-0 rounded-full bg-slate-200 px-2 py-0.5 text-[10px] text-slate-600">
                  {TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <span className="truncate text-sm">{m.name}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className={`chip ${m.status === "COMPLETED" ? "chip-green" : "chip-medium"}`}>
                  {statusText(m.status)}
                </span>
                {m.rebuild_required && <span className="text-[10px] text-amber-700">需刷新课程</span>}
                <button
                  onClick={() => removeMaterial(m.id, m.name)}
                  disabled={deletingId === m.id}
                  className="rounded-lg px-2 py-1 text-sm text-danger hover:bg-danger/10 disabled:opacity-50"
                  aria-label={`删除 ${m.name}`}
                >
                  {deletingId === m.id ? "…" : "🗑️"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {!materials.length && (
        <EmptyState icon="📂" title="还没有资料" hint="上传后 AI 会自动拆解知识图谱并生成题目" />
      )}

      <div className="pt-2">
        {processing && <Loading text="AI 正在解析资料…" />}
        {!processing && materials.length > 0 && readiness && !courseReady && (
          <p className="text-center text-sm text-muted">
            课程暂不可学习（{readiness.reason}），请确认至少有一份可读取的教材、课件或课堂笔记。
          </p>
        )}
        {courseReady && (
          <Link href={`/courses/${id}`} className="btn-primary block w-full">
            进入学习 →
          </Link>
        )}
      </div>
    </div>
  );
}
