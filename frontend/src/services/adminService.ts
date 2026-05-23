import { apiFetch } from "./apiClient";

export interface AdminUser {
  id: string | number;
  username: string;
  role: string;
  created_at: string;
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
