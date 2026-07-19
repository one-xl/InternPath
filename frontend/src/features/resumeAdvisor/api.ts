import type { AdvisorMessage, AdvisorRun, AdvisorSession, AdvisorSloDashboard, AdvisorSnapshot, ResumeBlock, ResumePreview, ResumeSuggestion, ResumeSummary } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "请求失败，请稍后重试。");
  }
  return response.json() as Promise<T>;
}

async function uploadResume(file: File): Promise<{ resumeFile: ResumeSummary }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/resumes/upload", { method: "POST", credentials: "include", body: form });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "简历上传失败，请稍后重试。");
  }
  return response.json() as Promise<{ resumeFile: ResumeSummary }>;
}

export const resumeAdvisorApi = {
  listResumes: async (): Promise<ResumeSummary[]> => (await request<{ resumes: ResumeSummary[] }>("/api/resumes")).resumes || [],
  uploadResume,
  deleteResume: (resumeId: string) => request<{ ok: boolean }>(`/api/resumes/${encodeURIComponent(resumeId)}`, { method: "DELETE" }),
  listSessions: async (): Promise<AdvisorSession[]> => (await request<{ sessions: AdvisorSession[] }>("/api/agent/resume/sessions")).sessions || [],
  getSloDashboard: (): Promise<AdvisorSloDashboard> => request("/api/agent/resume/operations/slo"),
  getSnapshot: (sessionId: string): Promise<AdvisorSnapshot> => request(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}`),
  getResumeView: (sessionId: string): Promise<{ blocks: ResumeBlock[]; preview: ResumePreview }> => request(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}/resume-view`),
  startSession: (data: { resumeId: string; jdText: string; title?: string }) => request<{ session: AdvisorSession; run: AdvisorRun }>("/api/agent/resume/sessions", {
    method: "POST",
    body: JSON.stringify({ resume_id: data.resumeId, jd_text: data.jdText, title: data.title || "" }),
  }),
  postMessage: (sessionId: string, content: string, clientMessageId: string, messageKind: "text" | "fact" = "text", remember = false) => request<{ duplicate: boolean; message: AdvisorMessage; run?: AdvisorRun; runId?: string }>(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, client_message_id: clientMessageId, message_kind: messageKind, remember }),
  }),
  actOnSuggestion: (suggestionId: string, action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback = "") => request<{ suggestion: ResumeSuggestion }>(`/api/agent/resume/suggestions/${encodeURIComponent(suggestionId)}/actions`, {
    method: "POST",
    body: JSON.stringify({ action, feedback }),
  }),
  finish: (sessionId: string) => request(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}/finish`, {
    method: "POST",
    body: JSON.stringify({ confirmation: "satisfied" }),
  }),
  cancelRun: (sessionId: string, runId: string) => request<{ id: string; status: string }>(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  }),
  deleteSession: (sessionId: string) => request<{ ok: boolean }>(`/api/agent/resume/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};
