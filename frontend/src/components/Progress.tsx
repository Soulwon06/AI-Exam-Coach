import type { ProgressMetrics } from "@/lib/types";

export default function ProgressBar({ value, color = "bg-primary" }: { value: number; color?: string }) {
  return (
    <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200">
      <div
        className={`h-full rounded-full ${color} transition-all`}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

export function MetricCard({ label, value, suffix = "%" }: { label: string; value: number; suffix?: string }) {
  return (
    <div className="card flex flex-col items-center gap-1">
      <span className="text-2xl font-extrabold text-slate-800">
        {value}
        {suffix}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}

export function ProgressPanel({ progress }: { progress: ProgressMetrics }) {
  return (
    <div className="card space-y-3">
      <div>
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="font-semibold">知识点覆盖</span>
          <span className="font-bold text-primary">{progress.coverage.toFixed(1)}%</span>
        </div>
        <ProgressBar value={progress.coverage} />
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="font-semibold">掌握程度</span>
          <span className="font-bold text-secondary">{progress.mastery.toFixed(1)}%</span>
        </div>
        <ProgressBar value={progress.mastery} color="bg-secondary" />
      </div>
      <div className="grid grid-cols-2 gap-2 pt-1">
        <MetricCard label="重点覆盖" value={progress.important_coverage} />
        <MetricCard label="重点掌握" value={progress.important_mastery} />
      </div>
    </div>
  );
}
