export const STUDENT_STATUS_LABELS: Record<string, string> = {
  REAL_EXAM_ACTIVE: "真题重点",
  NO_REAL_EXAM_EVIDENCE_CURRENT_CORPUS: "暂无真题证据 · 补充知识",
  REVIEW: "建议复习",
  WEAK: "需要加强",
  LEARNING: "学习中",
  MASTERED: "已通过练习验证",
  UNKNOWN: "尚未验证",
};

export function studentStatusLabel(value?: string | null, fallback = "尚未验证"): string {
  return (value && STUDENT_STATUS_LABELS[value]) || fallback;
}

export function priorityLabel(item: { exam_evidence_tier?: string | null }): string {
  return studentStatusLabel(item.exam_evidence_tier, "补充知识");
}

export function relativePriorityLabel(score?: number | null): string {
  return score == null ? "相对优先级 —" : `相对优先级 ${score.toFixed(2)}`;
}
