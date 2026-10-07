export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function userSafeError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : fallback;
  if (error.status === 401) return "登录状态已失效，请重新进入课程";
  if (error.status === 404) return "内容暂时不可用，请返回后重试";
  if (error.status === 410) return "本次练习已完成，请返回课程查看最新进度";
  if (error.status === 422) return error.message || "提交内容不符合要求，请检查后重试";
  if (error.status >= 500) return "服务暂时不可用，请稍后重试";
  if (error.status === 0) return "无法连接服务器，请确认后端已启动";
  return error.message || fallback;
}

const USER_ID_KEY = "aiec_user_id";

export function getUserId(): string {
  return typeof window === "undefined" ? "" : localStorage.getItem(USER_ID_KEY) || "";
}

export function setAuthenticatedUserId(id: string | null): void {
  if (typeof window === "undefined") return;
  if (id) localStorage.setItem(USER_ID_KEY, id);
  else localStorage.removeItem(USER_ID_KEY);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const base = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { ...options, headers, credentials: "include" });
  } catch {
    throw new ApiError("NETWORK_ERROR", "无法连接服务器，请确认后端已启动", 0);
  }

  const body = await res.json().catch(() => null);
  if (!res.ok || body?.error) {
    throw new ApiError(
      body?.error?.code || "UNKNOWN_ERROR",
      body?.error?.message || `请求失败 (${res.status})`,
      res.status,
    );
  }
  return body.data as T;
}

export function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
  return `${base}${path}`;
}

export function skipStudyUnit(studyUnitId: string): Promise<{ status: "SKIPPED" }> {
  return api<{ status: "SKIPPED" }>(`/study-units/${studyUnitId}/skip`, {
    method: "POST",
    body: "{}",
  });
}

export function masterStudyUnit(
  studyUnitId: string,
): Promise<import("./types").RecommendationStudyUnit & { self_assessed_mastery: true }> {
  return api<import("./types").RecommendationStudyUnit & { self_assessed_mastery: true }>(
    `/study-units/${studyUnitId}/master`,
    {
      method: "POST",
      body: "{}",
    },
  );
}

export function getCourseRanking(
  courseId: string,
  filters: { examEvidenceTier?: string } = {},
): Promise<import("./types").RankingData> {
  const query = new URLSearchParams({ offset: "0", limit: "367" });
  if (filters.examEvidenceTier) query.set("exam_evidence_tier", filters.examEvidenceTier);
  return api<import("./types").RankingData>(`/courses/${courseId}/ranking?${query.toString()}`);
}

export function retryWrongQuestion(
  courseId: string,
  questionId: string,
  studyUnitId: string,
): Promise<import("./types").StartSessionData> {
  return api<import("./types").StartSessionData>(`/courses/${courseId}/wrong-book/${questionId}/retry`, {
    method: "POST",
    body: JSON.stringify({ study_unit_id: studyUnitId }),
  });
}

export function startQuestionFirstSession(studyUnitId: string): Promise<import("./types").StartSessionData> {
  const request = requireContractRequest("startSessionRequest", studyUnitId);
  return api<import("./types").StartSessionData>(request.path, { method: request.method, body: request.body });
}

export function startLearningUsingPreference(studyUnitId: string): Promise<import("./types").StartSessionData> {
  const request = requireContractRequest("startLearningRequest", studyUnitId);
  return api<import("./types").StartSessionData>(request.path, { method: request.method, body: request.body });
}

export function startExplanationFirstSession(studyUnitId: string): Promise<import("./types").StartSessionData> {
  const request = requireContractRequest("startExplanationFirstRequest", studyUnitId);
  return api<import("./types").StartSessionData>(request.path, { method: request.method, body: request.body });
}

export function getNextQuestion(sessionId: string): Promise<import("./types").NextQuestionData> {
  return api<import("./types").NextQuestionData>(requireContractPath("nextQuestionPath", sessionId));
}

export function submitQuestionAnswer(
  questionId: string,
  payload: { session_id: string; answer: string; time_spent: number },
): Promise<import("./types").AnswerResult> {
  const request = requireContractRequest("answerRequest", questionId, payload);
  return api<import("./types").AnswerResult>(request.path, { method: request.method, body: request.body });
}

// Keep endpoint shapes in one small, dependency-free contract module so the frontend tests
// can verify the exact request body without introducing a browser test framework.
function requireContractRequest(name: string, ...args: unknown[]): { path: string; method: string; body: string } {
  const contract = CONTRACTS[name as keyof typeof CONTRACTS] as (...values: unknown[]) => { path: string; method: string; body: string };
  return contract(...args);
}

function requireContractPath(name: string, ...args: unknown[]): string {
  const contract = CONTRACTS[name as keyof typeof CONTRACTS] as (...values: unknown[]) => string;
  return contract(...args);
}

import {
  answerRequest,
  nextQuestionPath,
  startExplanationFirstRequest,
  startLearningRequest,
  startSessionRequest,
} from "./d5g-contract.mjs";

const CONTRACTS = { answerRequest, nextQuestionPath, startExplanationFirstRequest, startLearningRequest, startSessionRequest };
