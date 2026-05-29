import { apiFetch } from "./apiClient";

export interface AdminUser {
  id: string | number;
  username: string;
  role: string;
  created_at: string;
  is_active?: boolean;
  expires_at?: string | null;
  generation_limit?: number;
  remark?: string;
  assignment_count: number;
  usage_count: number;
  last_login?: string;
  assigned_models: string[];
}


export interface AdminModelConfig {
  id: string;
  provider: string;
  modelId: string;
  name: string;
  apiKey: string;
  enabled: boolean;
  owner_type: string;
  assignment_count: number;
  created_at: string;
  updated_at: string;
  [key: string]: any;
}

export interface AdminAssignment {
  id: string;
  user_id: string | number;
  username: string;
  enabled: boolean;
  created_at: string;
}

export interface UsageSummary {
  totalCalls: number;
  successCalls: number;
  failedCalls: number;
  avgLatency: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  byUser: Array<{ username: string; count: number }>;
  byModel: Array<{ modelId: string; count: number }>;
  byProvider: Array<{ provider: string; count: number }>;
  byDay: Array<{ day: string; count: number }>;
}

export interface UsageLog {
  id: string;
  userId: string | number;
  username: string;
  configId?: string;
  configName: string;
  provider: string;
  modelId: string;
  usageType?: string;
  endpoint?: string;
  success: boolean;
  errorType?: string;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  inputChars: number;
  outputChars: number;
  latencyMs: number;
  createdAt: string;
}

export interface UsageLogsResponse {
  logs: UsageLog[];
  totalCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export async function adminFetchUsers(): Promise<AdminUser[]> {
  const data = await apiFetch<{ users: AdminUser[] }>("/api/admin/users");
  return data.users || [];
}

export async function adminFetchConfigs(): Promise<AdminModelConfig[]> {
  const data = await apiFetch<{ configs: AdminModelConfig[] }>("/api/admin/model-configs");
  return data.configs || [];
}

export async function adminCreateConfig(config: {
  provider: string;
  modelId: string;
  name: string;
  apiKey: string;
  enabled?: boolean;
  config_json?: Record<string, any>;
}): Promise<{ id: string }> {
  return apiFetch<{ id: string }>("/api/admin/model-configs", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function adminUpdateConfig(
  id: string,
  config: {
    provider: string;
    modelId: string;
    name: string;
    apiKey?: string;
    enabled?: boolean;
    config_json?: Record<string, any>;
  }
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/model-configs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(config),
  });
}

export async function adminAssignConfig(id: string, userIds: Array<string | number>): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/model-configs/${encodeURIComponent(id)}/assign`, {
    method: "POST",
    body: JSON.stringify({ userIds }),
  });
}

export async function adminRevokeConfig(id: string, userIds: Array<string | number>): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/model-configs/${encodeURIComponent(id)}/revoke`, {
    method: "POST",
    body: JSON.stringify({ userIds }),
  });
}

export async function adminGetAssignments(id: string): Promise<AdminAssignment[]> {
  const data = await apiFetch<{ assignments: AdminAssignment[] }>(`/api/admin/model-configs/${encodeURIComponent(id)}/assignments`);
  return data.assignments || [];
}

export async function adminGetUsageSummary(params: {
  startDate?: string;
  endDate?: string;
  provider?: string;
  modelId?: string;
  userId?: string | number;
} = {}): Promise<UsageSummary> {
  const query = new URLSearchParams();
  if (params.startDate) query.append("startDate", params.startDate);
  if (params.endDate) query.append("endDate", params.endDate);
  if (params.provider) query.append("provider", params.provider);
  if (params.modelId) query.append("modelId", params.modelId);
  if (params.userId) query.append("userId", String(params.userId));

  const data = await apiFetch<{ summary: UsageSummary }>(`/api/admin/model-usage/summary?${query.toString()}`);
  return data.summary;
}

export async function adminGetUsageLogs(params: {
  startDate?: string;
  endDate?: string;
  provider?: string;
  modelId?: string;
  userId?: string | number;
  success?: boolean;
  page?: number;
  pageSize?: number;
} = {}): Promise<UsageLogsResponse> {
  const query = new URLSearchParams();
  if (params.startDate) query.append("startDate", params.startDate);
  if (params.endDate) query.append("endDate", params.endDate);
  if (params.provider) query.append("provider", params.provider);
  if (params.modelId) query.append("modelId", params.modelId);
  if (params.userId) query.append("userId", String(params.userId));
  if (params.success !== undefined) query.append("success", String(params.success));
  if (params.page !== undefined) query.append("page", String(params.page));
  if (params.pageSize !== undefined) query.append("pageSize", String(params.pageSize));

  return apiFetch<UsageLogsResponse>(`/api/admin/model-usage/logs?${query.toString()}`);
}

export interface GeneratedAccount {
  username: string;
  password: string;
  expires_at: string;
}

export async function adminGenerateTempAccounts(durationHours: number, quantity: number): Promise<GeneratedAccount[]> {
  const data = await apiFetch<{ ok: boolean; generated_accounts: GeneratedAccount[] }>("/api/admin/users/generate-temp", {
    method: "POST",
    body: JSON.stringify({ duration_hours: durationHours, quantity }),
  });
  return data.generated_accounts || [];
}

export async function adminUpdateUserStatus(userId: string | number, isActive: boolean): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/status`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function adminUpdateUserExpiry(userId: string | number, expiresAt: string | null): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/expiry`, {
    method: "PATCH",
    body: JSON.stringify({ expires_at: expiresAt }),
  });
}

export async function adminUpdateUserGenerationLimit(userId: string | number, limit: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/generation-limit`, {
    method: "PATCH",
    body: JSON.stringify({ generation_limit: limit }),
  });
}

export async function adminDeleteUser(userId: string | number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}`, {
    method: "DELETE",
  });
}

export async function adminDeleteExpiredUsers(): Promise<{ ok: boolean; deleted_count: number }> {
  return apiFetch<{ ok: boolean; deleted_count: number }>("/api/admin/users/expired", {
    method: "DELETE",
  });
}

export async function adminUpdateUsername(userId: string | number, username: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/username`, {
    method: "PATCH",
    body: JSON.stringify({ username }),
  });
}

export async function adminUpdateUserRemark(userId: string | number, remark: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/users/${encodeURIComponent(String(userId))}/remark`, {
    method: "PATCH",
    body: JSON.stringify({ remark }),
  });
}

export interface AdminAnnouncement {
  id?: string;
  title: string;
  content: string;
  start_time: string;
  end_time: string;
  target_type: 'all' | 'specific';
  target_users?: string;
  announcement_type?: 'top' | 'popup';
  show_behavior?: 'once' | 'every_login' | 'always';
  created_at?: string;
  updated_at?: string;
}

export async function adminFetchAnnouncements(): Promise<AdminAnnouncement[]> {
  const data = await apiFetch<{ announcements: AdminAnnouncement[] }>("/api/admin/announcements");
  return data.announcements || [];
}

export async function adminCreateAnnouncement(announcement: Omit<AdminAnnouncement, "id">): Promise<{ id: string; ok: boolean }> {
  return apiFetch<{ id: string; ok: boolean }>("/api/admin/announcements", {
    method: "POST",
    body: JSON.stringify(announcement),
  });
}

export async function adminUpdateAnnouncement(id: string, announcement: Omit<AdminAnnouncement, "id">): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/announcements/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(announcement),
  });
}

export async function adminDeleteAnnouncement(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/admin/announcements/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function fetchActiveAnnouncements(): Promise<AdminAnnouncement[]> {
  const data = await apiFetch<{ announcements: AdminAnnouncement[] }>("/api/announcements/active");
  return data.announcements || [];
}

