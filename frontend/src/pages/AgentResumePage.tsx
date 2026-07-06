import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, MouseEvent } from "react";
import { ResumeDiffView } from "../components/resume/ResumeDiffView";
import { useModelConfigs } from "../hooks/useModelConfigs";
import type { ChatModelConfig } from "../types/modelConfig";
import {
  buildActionPackMarkdown,
  buildApplicationSnippets,
  buildFactLedger,
  buildInterviewQuestions,
  buildJdRadar,
  buildResumeVariants,
  evaluateOfferDecision,
} from "../utils/agentInsights";
import { formatFileSize, validateResumeFile } from "../utils/fileValidation";

interface Resume {
  id: string;
  name: string;
  size: number;
  type: string;
  uploadedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

interface AgentLog {
  timestamp: string;
  type: "info" | "thought" | "tool_call" | "tool_response" | "warning" | "error";
  message: string;
  detail?: unknown;
  traceId?: string;
  stage?: string;
  agent?: string;
  status?: string;
  cacheNamespace?: string;
  cacheHit?: boolean | null;
  durationMs?: number | null;
  modelId?: string;
  providerCacheAvailable?: boolean;
  providerCacheHit?: boolean | null;
  providerCachedTokens?: number;
  providerCacheMissTokens?: number;
  providerInputTokens?: number;
  providerEndpointMode?: string;
  providerStream?: boolean | null;
  providerPromptCacheKey?: string;
  providerPromptCacheRetention?: string;
  providerPromptCacheDisabledReason?: string;
  retryCount?: number;
  errorType?: string;
  sequence?: number;
}

interface AgentTurn {
  id: string;
  taskId: string;
  stepIndex: number | null;
  role: "assistant" | "user" | string;
  content: string;
  answerType: AnswerType | "skip" | string;
  remember: boolean;
  evidenceScope: string;
  consumedAt: string;
  createdAt: string;
  summary?: string;
}

interface ModificationItem {
  section_name: string;
  section_index: number;
  original: string;
  new: string;
  reason: string;
}

interface CacheStatsItem {
  namespace: string;
  label: string;
  hit: boolean;
  savedModelCalls: number;
  stage?: string;
  agent?: string;
  timestamp?: string;
}

interface CacheStats {
  hits: number;
  misses: number;
  hitRate: number;
  savedModelCalls: number;
  items: CacheStatsItem[];
}

interface ProviderCacheStatsItem {
  stage: string;
  agent: string;
  modelId: string;
  hit: boolean;
  cachedTokens: number;
  cacheMissTokens: number;
  inputTokens: number;
  endpointMode?: string;
  stream?: boolean | null;
  promptCacheDisabledReason?: string;
  timestamp?: string;
}

interface ProviderCacheStats {
  checks: number;
  hits: number;
  misses: number;
  hitRate: number;
  cachedTokens: number;
  cacheMissTokens: number;
  inputTokens: number;
  items: ProviderCacheStatsItem[];
}

interface AgentConversationState {
  summary: string;
  globalPreferences: string[];
  factLedger: string[];
  updatedAt: string;
}

interface AgentStageMetric {
  traceId: string;
  stage: string;
  agent: string;
  status: string;
  durationMs: number;
  modelCalls: number;
  savedModelCalls: number;
  cacheHits: number;
  cacheMisses: number;
  cacheNamespace: string;
  retryCount: number;
  errorType: string;
  lastMessage: string;
  updatedAt: string;
}

interface AgentEventStreamMeta {
  snapshotBuildMs: number;
  artifactMode: "live" | "full" | string;
  pollIntervalMs: number;
}

interface AgentTask {
  task_id: string;
  trace_id?: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "WAITING_FOR_HUMAN";
  resume_id: string;
  original_resume_name: string;
  jd_text: string;
  logs: AgentLog[];
  optimized_resume_md: string;
  stream_preview_md: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  modification_diff_md: string;
  has_docx: boolean;
  modification_log: ModificationItem[];
  pending_question?: string;
  human_answer?: string;
  execution_plan?: string;
  execution_mode: AgentExecutionMode;
  tool_calling_mode: AgentToolCallingMode;
  conversation_turns: AgentTurn[];
  conversation_state: AgentConversationState;
  cache_stats: CacheStats;
  provider_cache_stats: ProviderCacheStats;
  stage_metrics: AgentStageMetric[];
  event_stream_meta: AgentEventStreamMeta;
}

type AnswerType = "evidence" | "preference" | "clarification" | "instruction" | "question";
type EvidenceScope = "current_step" | "resume" | "jd" | "global";
type ResultTab = "resume" | "diff" | "insights" | "diagnostics" | "logs";
type TerminalFilter = "all" | "thought" | "tool";
type CopyTarget = "resume" | "action-pack" | "text";
type AgentRunMode = "auto" | "copilot";
type AgentExecutionMode = "pipeline" | "agentic";
type AgentToolCallingMode = "auto" | "json_action" | "native_responses";

interface AgentProgressSnapshot {
  percent: number;
  title: string;
  currentAction: string;
  detail: string;
  recentActivities: string[];
  activeStage: string;
  isRunning: boolean;
}

interface SlashCommand {
  id: string;
  label: string;
  hint: string;
  answerType: AnswerType;
  evidenceScope: EvidenceScope;
  remember: boolean;
}

const terminalLabels: Record<TerminalFilter, string> = {
  all: "全部",
  thought: "说明",
  tool: "操作",
};

const executionModeLabels: Record<AgentExecutionMode, string> = {
  pipeline: "流水线",
  agentic: "Agentic",
};

const toolCallingModeLabels: Record<AgentToolCallingMode, string> = {
  auto: "自动",
  json_action: "JSON Action",
  native_responses: "原生工具",
};

const statusLabels: Record<AgentTask["status"], string> = {
  PENDING: "排队中",
  RUNNING: "优化中",
  COMPLETED: "已完成",
  FAILED: "失败",
  WAITING_FOR_HUMAN: "待确认",
};

const factStatusLabels = {
  verified: "已验证",
  review: "需确认",
};

const factSourceLabels = {
  resume: "原简历",
  jd_or_memory: "JD/记忆",
  needs_confirmation: "人工确认",
};

const offerScoreLabels = {
  compensation: "薪酬",
  growth: "成长",
  team: "团队",
  location: "地点",
  risk: "风险可控",
};

const answerTypeLabels: Record<AnswerType, string> = {
  evidence: "补充事实",
  preference: "表达偏好",
  clarification: "澄清问题",
  instruction: "修改指令",
  question: "追问原因",
};

const answerTypePlaceholders: Record<AnswerType, string> = {
  evidence: "例如：这个项目我负责接口设计和性能压测，最终把接口响应降到 200ms 左右。",
  preference: "例如：项目经历写得更克制一点，少用夸张形容词。",
  clarification: "例如：上一条补充只用于项目经历，不要写到技能里。",
  instruction: "例如：后续都按更简洁的风格写，教育经历不要改动。",
  question: "例如：为什么建议改这一段？这会不会显得经历被夸大？",
};

const evidenceScopeLabels: Record<EvidenceScope, string> = {
  current_step: "当前段落",
  resume: "整份简历",
  jd: "目标岗位",
  global: "长期偏好",
};

const slashCommands: SlashCommand[] = [
  {
    id: "evidence",
    label: "补充事实",
    hint: "给当前段落提供可核验事实",
    answerType: "evidence",
    evidenceScope: "current_step",
    remember: true,
  },
  {
    id: "instruction",
    label: "修改指令",
    hint: "告诉本次任务接下来怎么改",
    answerType: "instruction",
    evidenceScope: "resume",
    remember: true,
  },
  {
    id: "question",
    label: "追问原因",
    hint: "询问这次优化的判断依据",
    answerType: "question",
    evidenceScope: "current_step",
    remember: false,
  },
  {
    id: "preference",
    label: "长期偏好",
    hint: "保存投递表达偏好",
    answerType: "preference",
    evidenceScope: "global",
    remember: true,
  },
];

function friendlyProcessLabel(value?: string | number | null): string {
  if (value === undefined || value === null) return "";
  return String(value)
    .replace(/防幻觉/g, "事实核对")
    .replace(/段落改写/g, "段落调整")
    .replace(/JD 解码/g, "岗位要求读取")
    .replace(/执行计划/g, "处理计划")
    .replace(/AI/g, "")
    .replace(/大模型/g, "生成服务")
    .replace(/模型调用/g, "生成次数")
    .replace(/模型/g, "生成配置")
    .replace(/local_reuse/gi, "本地复用")
    .replace(/LocalReuse/g, "本地复用")
    .replace(/缓存/g, "复用")
    .replace(/stage/gi, "步骤")
    .trim();
}

function friendlyLogDetail(detail: unknown): string {
  const text = typeof detail === "string" ? detail : JSON.stringify(detail, null, 2);
  return friendlyProcessLabel(text);
}

function compactProcessMessage(message: string, limit = 140): string {
  const text = friendlyProcessLabel(message).replace(/\s+/g, " ").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit).trim()}...`;
}

function detailAsRecord(detail: unknown): Record<string, unknown> {
  return detail && typeof detail === "object" && !Array.isArray(detail)
    ? detail as Record<string, unknown>
    : {};
}

function readDetailText(detail: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = detail[key];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return "";
}

function readDetailNumber(detail: Record<string, unknown>, keys: string[]): number {
  for (const key of keys) {
    const value = Number(detail[key]);
    if (Number.isFinite(value)) return value;
  }
  return 0;
}

function summarizeJsonValue(value: unknown, limit = 180): string {
  if (value === undefined || value === null) return "";
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const normalized = friendlyProcessLabel(text).replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit).trim()}...`;
}

function getLogToolName(log: AgentLog): string {
  const detail = detailAsRecord(log.detail);
  const toolName = readDetailText(detail, ["tool_name", "toolName", "name"]);
  if (toolName) return toolName;
  const match = log.message.match(/tool:\s*([A-Za-z0-9_:-]+)/i);
  return match?.[1] || "";
}

function getToolResultData(log: AgentLog): Record<string, unknown> {
  const detail = detailAsRecord(log.detail);
  const result = detailAsRecord(detail.result);
  return detailAsRecord(result.data);
}

function getLiveEditSummary(log: AgentLog): { title: string; detail: string; status: string } | null {
  if (getLogToolName(log) !== "replace_resume_section") return null;
  const detail = detailAsRecord(log.detail);
  const args = detailAsRecord(detail.arguments);
  const data = getToolResultData(log);
  const sectionName = readDetailText(data, ["section_name", "sectionName"])
    || readDetailText(args, ["section_name", "sectionName"])
    || `段落 ${readDetailText(data, ["section_index", "sectionIndex"]) || readDetailText(args, ["section_index", "sectionIndex"]) || ""}`.trim();
  const reason = readDetailText(data, ["reason"]) || readDetailText(args, ["reason"]);
  const newPreview = readDetailText(data, ["new_preview", "newPreview"]) || readDetailText(args, ["new_content", "newContent"]);
  const isCall = log.type === "tool_call" || log.stage === "tool_call";
  return {
    title: isCall ? "正在现场修改" : "刚完成现场修改",
    detail: [
      sectionName ? `目标：${friendlyProcessLabel(sectionName)}` : "",
      reason ? `原因：${friendlyProcessLabel(reason)}` : "",
      newPreview ? `片段：${compactProcessMessage(newPreview, 92)}` : "",
    ].filter(Boolean).join(" · "),
    status: isCall ? "running" : "done",
  };
}

function getAgenticToolProgress(toolName: string): { percent: number; title: string; action: string; stage: string } {
  if (toolName === "list_workspace_files" || toolName === "read_workspace_file") {
    return { percent: 34, title: "读取上下文", action: "正在读取任务工作区文件", stage: "agentic-read" };
  }
  if (toolName === "extract_resume_sections") {
    return { percent: 46, title: "拆分简历", action: "正在拆分简历段落", stage: "agentic-section" };
  }
  if (toolName === "replace_resume_section" || toolName === "write_workspace_file") {
    return { percent: 66, title: "改写段落", action: "正在写入改写内容", stage: "agentic-rewrite" };
  }
  if (toolName === "generate_modification_diff") {
    return { percent: 78, title: "生成对照", action: "正在整理修改对照", stage: "agentic-diff" };
  }
  if (toolName === "ask_user_for_fact") {
    return { percent: 58, title: "等待确认", action: "正在请求用户补充事实", stage: "human-required" };
  }
  if (toolName === "finalize_resume_artifacts") {
    return { percent: 92, title: "生成产物", action: "正在回填模板并保存最终文件", stage: "agentic-finalize" };
  }
  return { percent: 52, title: "执行工具", action: "正在调用项目工具", stage: "agentic-tool" };
}

function logContains(log: AgentLog, patterns: string[]): boolean {
  const haystack = [
    log.message,
    log.stage,
    log.agent,
    log.cacheNamespace,
    typeof log.detail === "string" ? log.detail : JSON.stringify(log.detail || {}),
  ].join(" ");
  return patterns.some((pattern) => haystack.includes(pattern));
}

function logStageIs(log: AgentLog, stages: string[]): boolean {
  return stages.includes(String(log.stage || ""));
}

function isExportLog(log: AgentLog): boolean {
  if (logStageIs(log, ["export", "docx_export", "layout_audit", "finalize"])) return true;
  return logContains(log, [
    "正在利用原始简历模板",
    "成功生成高保真",
    "开始进行版面审计",
    "正在将 DOCX 转换",
    "版面审计完成",
    "优化流水线执行全部完成",
  ]);
}

function isModelStreamLog(log: AgentLog): boolean {
  return String(log.stage || "") === "model_stream_delta";
}

function isWorkerHeartbeatLog(log: AgentLog): boolean {
  return String(log.stage || "") === "worker_heartbeat";
}

function formatCount(value: number): string {
  return Number.isFinite(value) ? Math.max(0, Math.round(value)).toLocaleString("zh-CN") : "0";
}

function getModelStreamTotalChars(log: AgentLog): number {
  const detail = detailAsRecord(log.detail);
  const fromDetail = readDetailNumber(detail, ["total_chars", "totalChars"]);
  if (fromDetail > 0) return fromDetail;
  const match = String(log.message || "").match(/(\d+)\s+public characters/i);
  return match ? toNumber(match[1]) : 0;
}

function modelStreamDetail(log: AgentLog): string {
  const totalChars = getModelStreamTotalChars(log);
  return totalChars > 0
    ? `同一次模型请求正在流式返回公开动作，已接收 ${formatCount(totalChars)} 个字符。完整动作返回后才会解析并调用工具。`
    : "同一次模型请求正在流式返回公开动作；完整动作返回后才会解析并调用工具。";
}

function summarizeModelStreamLogs(logs: AgentLog[]): AgentLog | null {
  if (logs.length === 0) return null;
  const first = logs[0];
  const last = logs[logs.length - 1];
  const lastDetail = detailAsRecord(last.detail);
  const totalChars = Math.max(...logs.map(getModelStreamTotalChars), 0);
  return {
    ...last,
    timestamp: first.timestamp || last.timestamp,
    type: "thought",
    stage: "model_stream_delta",
    agent: last.agent || "AgenticToolLoop",
    status: last.status || "running",
    message: totalChars > 0
      ? `模型正在流式输出公开动作，已接收 ${formatCount(totalChars)} 个字符。`
      : "模型正在流式输出公开动作。",
    detail: {
      ...lastDetail,
      total_chars: totalChars,
      chunk_count: logs.length,
      first_timestamp: first.timestamp,
      latest_timestamp: last.timestamp,
    },
  };
}

function buildVisibleProcessLogs(logs: AgentLog[]): AgentLog[] {
  const visible: AgentLog[] = [];
  let streamBuffer: AgentLog[] = [];

  const flushStream = () => {
    const summary = summarizeModelStreamLogs(streamBuffer);
    if (summary) visible.push(summary);
    streamBuffer = [];
  };

  logs.forEach((log) => {
    if (isModelStreamLog(log)) {
      streamBuffer.push(log);
      return;
    }
    flushStream();
    if (isWorkerHeartbeatLog(log)) return;
    visible.push(log);
  });
  flushStream();
  return visible;
}

function buildAgentProgress(task: AgentTask | null): AgentProgressSnapshot {
  if (!task) {
    return {
      percent: 0,
      title: "等待任务",
      currentAction: "选择简历和 JD 后开始处理",
      detail: "后台尚未启动。",
      recentActivities: [],
      activeStage: "idle",
      isRunning: false,
    };
  }

  const logs = task.logs || [];
  const hasLog = (patterns: string[]) => logs.some((log) => logContains(log, patterns));
  const hasStage = (stages: string[]) => logs.some((log) => logStageIs(log, stages));
  const hasLocalReuseMiss = (namespace: string) => logs.some((log) => log.cacheNamespace === namespace && log.cacheHit === false);
  const hasLocalReuseHit = (namespace: string) => logs.some((log) => log.cacheNamespace === namespace && log.cacheHit === true);
  const lastLog = logs[logs.length - 1];
  const latestModelStreamLog = [...logs].reverse().find(isModelStreamLog);
  const planIsGenerating = logs.some((log) => (
    log.cacheNamespace === "resume_plan_v3"
    && log.cacheHit === false
    && (log.status === "running" || log.stage === "plan" || logContains(log, ["plan_generation_started", "生成处理计划", "生成执行计划"]))
  ));

  let percent = task.status === "PENDING" ? 3 : 6;
  let title = task.status === "PENDING" ? "等待后台接手" : "后台处理中";
  let currentAction = task.status === "PENDING" ? "任务已创建，等待 worker 启动" : "正在初始化任务";
  let detail = "系统会实时同步后台日志。";
  let activeStage = "pending";

  const advance = (nextPercent: number, nextTitle: string, nextAction: string, nextDetail: string, nextStage: string) => {
    if (nextPercent >= percent) {
      percent = nextPercent;
      title = nextTitle;
      currentAction = nextAction;
      detail = nextDetail;
      activeStage = nextStage;
    }
  };

  const latestStageLog = [...logs].reverse().find((log) => {
    const stage = String(log.stage || "");
    return stage && stage !== "unknown";
  });
  const snapshotFromLatestLog = (log: AgentLog | undefined): AgentProgressSnapshot | null => {
    if (!log) return null;
    const stage = String(log.stage || "");
    const message = compactProcessMessage(log.message, 180);
    const snapshot = (
      nextPercent: number,
      nextTitle: string,
      nextAction: string,
      nextDetail: string,
      nextStage: string,
    ): AgentProgressSnapshot => ({
      percent: nextPercent,
      title: nextTitle,
      currentAction: nextAction,
      detail: message || nextDetail,
      recentActivities: [],
      activeStage: nextStage,
      isRunning: true,
    });

    if (stage === "stream_connected") return snapshot(5, "连接事件流", "正在同步任务首包", "浏览器已连接实时事件流。", "stream-connected");
    if (stage === "bootstrap") return snapshot(8, "创建任务", "正在本地预热简历和 JD", "后端已收到任务，正在写入轻量工作区。", "bootstrap");
    if (stage === "workspace_prewarm") return snapshot(12, "预热完成", "简历、JD 和预览已准备好", "页面可以先展示预热结果，后台继续接手。", "workspace-prewarm");
    if (stage === "queue") return snapshot(15, "进入队列", "正在等待后台 worker 秒级接手", "任务已提交到 RQ 队列。", "queue");
    if (stage === "queue_wait") return snapshot(16, "等待 worker", "队列仍在等待消费", "如果持续较久，请检查 RQ worker 是否运行。", "queue-wait");
    if (stage === "worker_start") return snapshot(18, "worker 已接手", "正在启动 Agent 执行链", "后台 worker 已抢到运行锁。", "worker-start");
    if (stage === "worker_heartbeat") return snapshot(24, "后台处理中", "正在等待下一条执行日志", "后台任务仍在运行。", "worker-heartbeat");
    if (stage === "worker_lock") return snapshot(18, "已有运行实例", "正在复用当前运行中的任务", "后台检测到重复执行并已跳过。", "worker-lock");
    if (stage === "retry") return snapshot(8, "准备重试", "正在恢复失败点", "后台正在重新发送失败时的同一份数据。", "retry");
    if (stage === "resume_load") return snapshot(14, "读取简历", "正在读取简历正文", "后台正在从数据库读取解析后的简历文本和原始文件。", "resume-load");
    if (stage === "jd_load") return snapshot(17, "读取 JD", "正在读取目标岗位 JD", "后台正在检查 JD 文本长度。", "jd-load");
    if (stage === "workspace") return snapshot(20, "准备工作区", "正在写入任务文件", "后台正在准备流式预览和导出工作区。", "workspace");
    if (stage === "style") return snapshot(22, "抽取格式", "正在提取原始排版", "后台正在读取 DOCX 样式和模板特征。", "style");
    if (stage === "model_config") return snapshot(25, "连接模型", "正在解析模型配置", "后台正在确认本次模型和接口模式。", "model");
    if (stage === "agentic_bootstrap") return snapshot(27, "启动 Agentic", "正在准备模型工具循环", "后台正在把简历、JD 和工具注册表交给受控 Agent。", "agentic-bootstrap");
    if (stage === "model_turn") return snapshot(38, "模型思考", "正在等待模型决定下一步", "后台正在通过 Responses 流式接口读取模型输出。", "agentic-model-turn");
    if (stage === "model_stream_delta") return snapshot(41, "模型流式输出", "正在接收模型公开动作", modelStreamDetail(log), "agentic-model-stream");
    if (stage === "model_delta") return snapshot(44, "接收输出", "正在接收模型流式输出", "后台正在解析模型返回的动作或最终文本。", "agentic-model-delta");
    if (stage === "tool_call" || stage === "tool_result") {
      const toolProgress = getAgenticToolProgress(getLogToolName(log));
      return snapshot(
        stage === "tool_result" ? Math.min(toolProgress.percent + 3, 96) : toolProgress.percent,
        toolProgress.title,
        stage === "tool_result" ? "项目工具已返回结果" : toolProgress.action,
        "后台正在把工具结果继续交还给模型，直到产物完成。",
        toolProgress.stage,
      );
    }
    if (stage === "provider_usage") return snapshot(50, "记录用量", "正在读取大模型 usage 和缓存统计", "后台正在记录 cached_tokens、input tokens 和 stream 模式。", "provider-usage");
    if (stage === "human_required") return snapshot(58, "等待确认", "需要用户补充事实", "模型遇到不能自行确认的信息，已暂停生成。", "human-required");
    if (stage === "preference_context") return snapshot(28, "读取偏好", "正在读取会话摘要、偏好和事实上下文", "这些上下文会参与计划和改写。", "preference-context");
    if (stage === "plan") {
      const done = logContains(log, ["完成", "生成完毕", "已存入数据库"]);
      return snapshot(done ? 42 : 34, done ? "计划完成" : "生成计划", done ? "处理计划已生成" : "模型正在生成处理计划", "后台正在等待模型返回可执行步骤。", done ? "plan-complete" : "plan-generating");
    }
    if (stage === "job_decode") return snapshot(52, "读取岗位", "正在解码 JD，提取岗位画像", "后台正在把岗位要求转成改写可用的结构。", "job-decode");
    if (stage === "section") return snapshot(60, "处理段落", "正在定位要优化的简历模块", "后台正在遍历执行计划。", "section");
    if (stage === "rewrite") return snapshot(68, "改写段落", "正在逐段改写简历内容", "页面预览会随流式输出更新。", "rewrite");
    if (stage === "rewrite_retry") return snapshot(74, "修正段落", "正在根据审计或事实守门反馈修正", "后台正在移除风险表达或优化质量。", "rewrite-retry");
    if (stage === "hr_critic") return snapshot(78, "质量审计", "正在做 HR 视角审计", "后台正在检查表达质量和岗位匹配度。", "critic");
    if (stage === "fact_guard") return snapshot(84, "事实核对", "正在做本地事实边界检测", "后台正在核对新增数字、日期和机构名称。", "fact-guard");
    if (stage === "hallucination") return snapshot(86, "语义复核", "正在做 LLM 防幻觉复核", "后台正在复核是否存在过度包装。", "verify");
    if (stage === "docx_export") return snapshot(92, "生成 DOCX", "正在回填原始模板", "后台正在保留照片、段落和模板元素。", "docx-export");
    if (stage === "layout_audit") return snapshot(96, "版面审计", "正在检查导出版面", "后台正在转换并检查 DOCX/PDF 视觉版面。", "layout-audit");
    if (stage === "finalize") return snapshot(98, "收尾", "正在保存最终结果", "后台正在写入最终产物。", "finalize");
    return null;
  };

  if (logs.length > 0) {
    advance(8, "读取上下文", "正在读取任务记录", "后台已接手任务，正在确认任务、简历和 JD 是否可用。", "bootstrap");
  }
  if (hasStage(["workspace_prewarm"])) {
    advance(12, "预热完成", "简历、JD 和预览已准备好", "页面可以先展示预热结果，后台继续接手。", "workspace-prewarm");
  }
  if (hasStage(["queue", "queue_wait"])) {
    advance(15, "进入队列", "正在等待后台 worker 秒级接手", "任务已提交到后台队列。", "queue");
  }
  if (hasStage(["worker_start"])) {
    advance(18, "worker 已接手", "正在启动 Agent 执行链", "后台 worker 已抢到运行锁并切换到运行态。", "worker-start");
  }
  if (hasStage(["resume_load"])) {
    advance(14, "读取简历", "正在读取简历正文", "后台正在从数据库读取解析后的简历文本和原始文件。", "resume-load");
  }
  if (hasStage(["jd_load"])) {
    advance(17, "读取 JD", "正在读取目标岗位 JD", "后台正在检查 JD 文本长度，并准备后续岗位画像解析。", "jd-load");
  }
  if (hasStage(["workspace"])) {
    advance(20, "准备工作区", "正在写入简历、JD 和原始文件", "后台正在准备后续分段、流式预览和导出所需的工作文件。", "workspace");
  }
  if (hasStage(["style"]) || hasLog(["style_profile", "排版特征"])) {
    advance(22, "抽取格式", "正在提取原始简历样式和排版特征", "这一步会给后续 DOCX 导出保留模板依据。", "style");
  }
  if (hasStage(["model_config"]) || hasLog(["模型配置", "当前模型"])) {
    advance(25, "连接模型", "正在解析本次使用的大模型配置", "后台已准备好模型客户端，接下来会检查可复用结果。", "model");
  }
  if (hasStage(["agentic_bootstrap"])) {
    advance(27, "启动 Agentic", "正在准备模型工具循环", "后台正在把简历、JD 和工具注册表交给受控 Agent。", "agentic-bootstrap");
  }
  if (hasStage(["model_turn"])) {
    advance(38, "模型思考", "正在等待模型决定下一步", "这是一次真实的大模型请求；完整公开动作返回后才会调用工具。", "agentic-model-turn");
  }
  if (latestModelStreamLog) {
    advance(41, "模型流式输出", "正在接收模型公开动作", modelStreamDetail(latestModelStreamLog), "agentic-model-stream");
  }
  if (hasStage(["model_delta"])) {
    advance(44, "解析模型动作", "正在解析模型返回的公开动作", "后台正在把完整输出解析成下一次工具调用或最终回答。", "agentic-model-delta");
  }
  if (hasStage(["provider_usage"])) {
    advance(50, "记录用量", "正在读取大模型 usage 和缓存统计", "后台正在记录 cached tokens、input tokens 和 stream 模式。", "provider-usage");
  }
  if (hasStage(["preference_context"])) {
    advance(28, "读取偏好", "正在读取会话摘要、偏好和事实上下文", "这些上下文会参与处理计划和后续逐段改写。", "preference-context");
  }
  if (hasLocalReuseHit("resume_plan_v3")) {
    advance(36, "复用计划", "已复用本地处理计划，正在跳过计划生成", "后台会直接进入岗位解码和段落处理。", "plan-local-reuse-hit");
  }
  if (hasLocalReuseMiss("resume_plan_v3")) {
    advance(30, "生成计划", "没有可本地复用的处理计划，正在准备生成", "后台正在整理简历、JD 和偏好上下文。", "plan-local-reuse-miss");
  }
  if (planIsGenerating) {
    advance(34, "生成计划", "模型正在生成处理计划", "这一步通常最安静：后台正在等待模型返回可执行步骤。", "plan-generating");
  }
  if (hasLog(["执行计划模型调用完成", "计划模型调用完成", "执行计划生成完毕", "优化执行计划生成完毕"])) {
    advance(42, "计划完成", "处理计划已生成，正在写入数据库", "接下来会读取岗位要求并进入逐段优化。", "plan-complete");
  }
  if (hasLocalReuseMiss("job_decode_v2") || hasStage(["job_decode"]) || hasLog(["JD 解码", "岗位解码", "岗位画像"])) {
    advance(52, "读取岗位", "正在解码 JD，提取岗位画像", "后台正在把岗位要求转成后续改写可用的结构。", "job-decode");
  }
  if (hasStage(["section", "rewrite"]) || hasLog(["段落", "改写", "rewrite", "ResumeCopywriter"])) {
    advance(68, "改写段落", "正在逐段改写简历内容", "页面中的预览会随着后台流式写入逐步更新。", "rewrite");
  }
  if (hasStage(["hr_critic"]) || hasLog(["HR", "审计", "critic", "Critic"])) {
    advance(78, "质量审计", "正在做 HR 视角审计", "后台会检查表达是否贴合 JD、是否过度包装。", "critic");
  }
  if (hasStage(["hallucination", "fact_guard"]) || hasLog(["防幻觉", "事实", "核对", "hallucination", "verification"])) {
    advance(86, "事实核对", "正在核对事实和证据边界", "如果发现无法确认的信息，会暂停并向你提问。", "verify");
  }
  if (logs.some(isExportLog)) {
    advance(94, "生成文件", "正在生成 DOCX/PDF 并检查版面", "后台正在处理最终导出和视觉检查。", "export");
  }

  if (task.status === "RUNNING") {
    const liveSnapshot = snapshotFromLatestLog(latestStageLog);
    if (liveSnapshot && liveSnapshot.percent >= percent) {
      percent = liveSnapshot.percent;
      title = liveSnapshot.title;
      currentAction = liveSnapshot.currentAction;
      detail = liveSnapshot.detail;
      activeStage = liveSnapshot.activeStage;
    }
  }

  if (task.status === "WAITING_FOR_HUMAN") {
    advance(Math.max(percent, 88), "等待确认", "后台需要你补充或确认信息", task.pending_question || "请查看下方对话框。", "waiting");
  } else if (task.status === "COMPLETED") {
    advance(100, "处理完成", "投递版本已生成", "可以下载 DOCX/PDF 或继续追问。", "completed");
  } else if (task.status === "FAILED") {
    title = "处理失败";
    currentAction = task.error_message || "后台执行失败";
    detail = lastLog?.message ? compactProcessMessage(lastLog.message, 180) : "可以从失败点重试。";
    activeStage = "failed";
  }

  const recentActivities = buildVisibleProcessLogs(logs)
    .slice(-5)
    .reverse()
    .map((log) => compactProcessMessage(log.message, 90))
    .filter(Boolean);

  if (lastLog && task.status === "RUNNING" && activeStage !== "plan-generating") {
    if (isModelStreamLog(lastLog)) {
      detail = modelStreamDetail(lastLog);
    } else if (!isWorkerHeartbeatLog(lastLog)) {
      detail = compactProcessMessage(lastLog.message, 180);
    }
  }

  return {
    percent: Math.max(0, Math.min(100, percent)),
    title,
    currentAction,
    detail,
    recentActivities,
    activeStage,
    isRunning: task.status === "PENDING" || task.status === "RUNNING",
  };
}

function AgentProcessLogLine({
  log,
  isFailurePoint,
  isRetryingTask,
  onRetry,
}: {
  log: AgentLog;
  isFailurePoint: boolean;
  isRetryingTask: boolean;
  onRetry: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const detailRecord = detailAsRecord(log.detail);
  const message = friendlyProcessLabel(log.message);
  const compactMessage = compactProcessMessage(log.message);
  const detailText = log.detail === undefined || log.detail === null ? "" : friendlyLogDetail(log.detail);
  const hasLongMessage = message !== compactMessage;
  const hasDetail = detailText.trim().length > 0 && detailText !== "{}";
  const canExpand = hasLongMessage || hasDetail;
  const toolName = getLogToolName(log);
  const isToolCall = log.type === "tool_call" || log.stage === "tool_call";
  const isToolResult = log.type === "tool_response" || log.stage === "tool_result";
  const isProviderUsage = log.stage === "provider_usage" || Boolean(log.providerEndpointMode);
  const isModelStream = isModelStreamLog(log);
  const toolArguments = detailRecord.arguments ?? detailRecord.args;
  const toolResult = detailRecord.result ?? detailRecord.data;
  const toolPreview = readDetailText(detailRecord, ["preview", "error"]) || summarizeJsonValue(toolResult, 220);
  const liveEdit = getLiveEditSummary(log);
  const toolResultData = getToolResultData(log);
  const editedSectionName = readDetailText(toolResultData, ["section_name", "sectionName"]);
  const editedPreview = readDetailText(toolResultData, ["new_preview", "newPreview"]);
  const toolOk = detailRecord.ok === undefined ? log.type !== "error" : Boolean(detailRecord.ok);
  const detailDurationMs = readDetailNumber(detailRecord, ["duration_ms", "durationMs"]) || toNumber(log.durationMs);
  const streamTotalChars = getModelStreamTotalChars(log);
  const streamChunkCount = readDetailNumber(detailRecord, ["chunk_count", "chunkCount"]);
  const cardMode = isModelStream ? "模型输出" : isToolCall ? "调用工具" : isToolResult ? "工具结果" : isProviderUsage ? "模型用量" : "";
  const cardTitle = isProviderUsage
    ? (log.providerEndpointMode === "responses" ? "Responses API" : log.providerEndpointMode || log.modelId || "模型调用")
    : isModelStream
      ? "公开动作流"
    : toolName || friendlyProcessLabel(log.stage || log.agent || "处理步骤");
  const lineClassName = [
    "agent-process-line",
    `is-${log.type}`,
    isToolCall || isToolResult ? "is-tool-card" : "",
    isProviderUsage ? "is-provider-card" : "",
    isModelStream ? "is-model-stream-card" : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={lineClassName}>
      <time>{formatTime(log.timestamp)}</time>
      <div className="agent-process-body">
        {(isToolCall || isToolResult || isProviderUsage || isModelStream) && (
          <div className="agent-process-event-card">
            <div className="agent-process-event-main">
              <em>{cardMode}</em>
              <strong>{friendlyProcessLabel(cardTitle)}</strong>
              {(isToolCall || isToolResult) && (
                <span className={toolOk ? "is-ok" : "is-failed"}>{isToolCall ? "发送中" : toolOk ? "成功" : "失败"}</span>
              )}
              {isModelStream && <span className="is-muted">同一次请求</span>}
              {isProviderUsage && (
                <span className={log.providerCacheHit ? "is-ok" : "is-muted"}>
                  {log.providerCacheAvailable ? (log.providerCacheHit ? "缓存命中" : "未命中") : "已记录"}
                </span>
              )}
            </div>
            <div className="agent-process-event-metrics">
              {(isToolCall || isToolResult) && toolArguments !== undefined && (
                <span>参数 {summarizeJsonValue(toolArguments, 80) || "{}"}</span>
              )}
              {liveEdit && <span>{liveEdit.title}</span>}
              {editedSectionName && <span>段落 {friendlyProcessLabel(editedSectionName)}</span>}
              {editedPreview && <span>片段 {compactProcessMessage(editedPreview, 96)}</span>}
              {isToolResult && toolPreview && <span>结果 {summarizeJsonValue(toolPreview, 120)}</span>}
              {detailDurationMs > 0 && <span>{detailDurationMs}ms</span>}
              {isModelStream && streamTotalChars > 0 && <span>已接收 {formatCount(streamTotalChars)} 字符</span>}
              {isModelStream && streamChunkCount > 1 && <span>合并 {streamChunkCount} 个片段</span>}
              {isModelStream && <span>等待完整动作后调用工具</span>}
              {isProviderUsage && log.providerEndpointMode && (
                <span>{log.providerEndpointMode === "responses" ? "Responses" : "Chat Completions"}{log.providerStream ? " stream=true" : log.providerStream === false ? " stream=false" : ""}</span>
              )}
              {isProviderUsage && log.providerInputTokens !== undefined && <span>input {log.providerInputTokens} tokens</span>}
              {isProviderUsage && log.providerCacheAvailable && <span>cached {log.providerCachedTokens || 0} tokens</span>}
              {isProviderUsage && log.providerPromptCacheRetention && <span>retention {log.providerPromptCacheRetention}</span>}
            </div>
          </div>
        )}
        <span className="agent-process-message" title={message}>
          {expanded ? message : compactMessage}
        </span>
        {(log.stage || log.agent || log.providerEndpointMode || log.providerPromptCacheDisabledReason || (log.cacheHit !== null && log.cacheHit !== undefined) || log.providerCacheAvailable) && (
          <small>
            {[log.stage, log.agent].map(friendlyProcessLabel).filter(Boolean).join(" · ")}
            {log.cacheHit === true ? " · 本地复用" : ""}
            {log.cacheHit === false ? " · 本地新算" : ""}
            {log.providerEndpointMode ? ` · ${log.providerEndpointMode === "responses" ? "Responses" : "Chat Completions"}${log.providerStream === null || log.providerStream === undefined ? "" : log.providerStream ? " stream=true" : " stream=false"}` : ""}
            {log.providerCacheAvailable ? ` · ${log.providerCacheHit ? "大模型缓存命中" : "大模型缓存未命中"} ${log.providerCachedTokens || 0} tokens` : ""}
            {log.providerPromptCacheDisabledReason ? " · Provider rejected Prompt Cache fields" : ""}
          </small>
        )}
        {expanded && hasDetail && (
          <pre className="agent-process-detail">{detailText}</pre>
        )}
        {canExpand && (
          <button
            type="button"
            className="agent-process-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "收回" : "展开"}
          </button>
        )}
        {isFailurePoint && (
          <button
            type="button"
            className="agent-inline-retry"
            onClick={onRetry}
            disabled={isRetryingTask}
          >
            {isRetryingTask ? "正在重试..." : "重试这一点"}
          </button>
        )}
      </div>
    </div>
  );
}

function parseApiError(response: Response, fallback: string): Promise<string> {
  return response.json()
    .then((body: { detail?: string }) => body.detail || fallback)
    .catch(() => fallback);
}

function parseLogs(raw: unknown): AgentLog[] {
  if (!raw) return [];
  const normalize = (items: any[]): AgentLog[] => items
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      ...item,
      providerCacheAvailable: Boolean(item.providerCacheAvailable),
      providerCacheHit: item.providerCacheHit === null || item.providerCacheHit === undefined ? null : Boolean(item.providerCacheHit),
      providerCachedTokens: toNumber(item.providerCachedTokens),
      providerCacheMissTokens: toNumber(item.providerCacheMissTokens),
      providerInputTokens: toNumber(item.providerInputTokens),
      providerEndpointMode: item.providerEndpointMode ? String(item.providerEndpointMode) : "",
      providerStream: item.providerStream === null || item.providerStream === undefined ? null : Boolean(item.providerStream),
      providerPromptCacheKey: item.providerPromptCacheKey ? String(item.providerPromptCacheKey) : "",
      providerPromptCacheRetention: item.providerPromptCacheRetention ? String(item.providerPromptCacheRetention) : "",
      providerPromptCacheDisabledReason: item.providerPromptCacheDisabledReason ? String(item.providerPromptCacheDisabledReason) : "",
      sequence: item.sequence === null || item.sequence === undefined ? undefined : toNumber(item.sequence),
    }));
  if (Array.isArray(raw)) return normalize(raw);
  if (typeof raw !== "string") return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? normalize(parsed) : [];
  } catch {
    return [];
  }
}

function emptyCacheStats(): CacheStats {
  return {
    hits: 0,
    misses: 0,
    hitRate: 0,
    savedModelCalls: 0,
    items: [],
  };
}

function toNumber(value: unknown): number {
  const next = Number(value);
  return Number.isFinite(next) ? next : 0;
}

function normalizeAgentExecutionMode(value: unknown): AgentExecutionMode {
  return String(value || "").trim().toLowerCase().replace("-", "_") === "agentic" ? "agentic" : "pipeline";
}

function normalizeAgentToolCallingMode(value: unknown): AgentToolCallingMode {
  const normalized = String(value || "").trim().toLowerCase().replace("-", "_");
  if (normalized === "json_action" || normalized === "native_responses") return normalized;
  return "auto";
}

function parseCacheStats(raw: any): CacheStats {
  if (!raw || typeof raw !== "object") return emptyCacheStats();
  const rawItems = Array.isArray(raw.items) ? raw.items : [];
  const items = rawItems
    .filter((item: any) => item && typeof item === "object")
    .map((item: any) => ({
      namespace: String(item.namespace || ""),
      label: String(item.label || item.namespace || "cache"),
      hit: Boolean(item.hit),
      savedModelCalls: toNumber(item.savedModelCalls),
      stage: item.stage ? String(item.stage) : "",
      agent: item.agent ? String(item.agent) : "",
      timestamp: item.timestamp ? String(item.timestamp) : "",
    }));
  return {
    hits: toNumber(raw.hits),
    misses: toNumber(raw.misses),
    hitRate: toNumber(raw.hitRate),
    savedModelCalls: toNumber(raw.savedModelCalls),
    items,
  };
}

function emptyProviderCacheStats(): ProviderCacheStats {
  return {
    checks: 0,
    hits: 0,
    misses: 0,
    hitRate: 0,
    cachedTokens: 0,
    cacheMissTokens: 0,
    inputTokens: 0,
    items: [],
  };
}

function parseProviderCacheStats(raw: any): ProviderCacheStats {
  if (!raw || typeof raw !== "object") return emptyProviderCacheStats();
  const rawItems = Array.isArray(raw.items) ? raw.items : [];
  return {
    checks: toNumber(raw.checks),
    hits: toNumber(raw.hits),
    misses: toNumber(raw.misses),
    hitRate: toNumber(raw.hitRate),
    cachedTokens: toNumber(raw.cachedTokens),
    cacheMissTokens: toNumber(raw.cacheMissTokens),
    inputTokens: toNumber(raw.inputTokens),
    items: rawItems
      .filter((item: any) => item && typeof item === "object")
      .map((item: any) => ({
        stage: String(item.stage || ""),
        agent: String(item.agent || ""),
        modelId: String(item.modelId || ""),
        hit: Boolean(item.hit),
        cachedTokens: toNumber(item.cachedTokens),
        cacheMissTokens: toNumber(item.cacheMissTokens),
        inputTokens: toNumber(item.inputTokens),
        endpointMode: item.endpointMode ? String(item.endpointMode) : "",
        stream: item.stream === null || item.stream === undefined ? null : Boolean(item.stream),
        promptCacheDisabledReason: item.promptCacheDisabledReason ? String(item.promptCacheDisabledReason) : "",
        timestamp: item.timestamp ? String(item.timestamp) : "",
      })),
  };
}

function parseConversationTurns(raw: any): AgentTurn[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((turn) => turn && typeof turn === "object")
    .map((turn) => ({
      id: String(turn.id || ""),
      taskId: String(turn.taskId || ""),
      stepIndex: turn.stepIndex === null || turn.stepIndex === undefined ? null : toNumber(turn.stepIndex),
      role: String(turn.role || ""),
      content: String(turn.content || ""),
      answerType: String(turn.answerType || ""),
      remember: Boolean(turn.remember),
      evidenceScope: String(turn.evidenceScope || ""),
      consumedAt: String(turn.consumedAt || ""),
      createdAt: String(turn.createdAt || ""),
      summary: String(turn.summary || ""),
    }));
}

function parseConversationState(raw: any): AgentConversationState {
  if (!raw || typeof raw !== "object") {
    return { summary: "", globalPreferences: [], factLedger: [], updatedAt: "" };
  }
  return {
    summary: String(raw.summary || ""),
    globalPreferences: Array.isArray(raw.globalPreferences) ? raw.globalPreferences.map(String) : [],
    factLedger: Array.isArray(raw.factLedger) ? raw.factLedger.map(String) : [],
    updatedAt: String(raw.updatedAt || ""),
  };
}

function parseStageMetrics(raw: any): AgentStageMetric[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      traceId: String(item.traceId || ""),
      stage: String(item.stage || "unknown"),
      agent: String(item.agent || ""),
      status: String(item.status || ""),
      durationMs: toNumber(item.durationMs),
      modelCalls: toNumber(item.modelCalls),
      savedModelCalls: toNumber(item.savedModelCalls),
      cacheHits: toNumber(item.cacheHits),
      cacheMisses: toNumber(item.cacheMisses),
      cacheNamespace: String(item.cacheNamespace || ""),
      retryCount: toNumber(item.retryCount),
      errorType: String(item.errorType || ""),
      lastMessage: String(item.lastMessage || ""),
      updatedAt: String(item.updatedAt || ""),
    }));
}

function parseEventStreamMeta(raw: any): AgentEventStreamMeta {
  if (!raw || typeof raw !== "object") {
    return { snapshotBuildMs: 0, artifactMode: "", pollIntervalMs: 0 };
  }
  return {
    snapshotBuildMs: toNumber(raw.snapshotBuildMs),
    artifactMode: raw.artifactMode ? String(raw.artifactMode) : "",
    pollIntervalMs: toNumber(raw.pollIntervalMs),
  };
}

function mapTaskFromApi(task: any): AgentTask {
  return {
    task_id: task.taskId,
    trace_id: task.traceId || "",
    status: task.status,
    resume_id: task.resumeId,
    original_resume_name: task.originalResumeName,
    jd_text: task.jdText,
    logs: parseLogs(task.logs),
    optimized_resume_md: task.optimizedResumeMd || "",
    stream_preview_md: task.streamPreviewMd || "",
    error_message: task.errorMessage || "",
    created_at: task.createdAt,
    updated_at: task.updatedAt,
    modification_diff_md: task.modificationDiffMd || "",
    has_docx: Boolean(task.hasDocx),
    modification_log: Array.isArray(task.modificationLog)
      ? task.modificationLog
        .map(normalizeModificationItem)
        .filter((item: ModificationItem | null): item is ModificationItem => Boolean(item))
      : [],
    pending_question: task.pendingQuestion || "",
    human_answer: task.humanAnswer || "",
    execution_plan: task.executionPlan || "",
    execution_mode: normalizeAgentExecutionMode(task.executionMode || task.execution_mode),
    tool_calling_mode: normalizeAgentToolCallingMode(task.toolCallingMode || task.tool_calling_mode),
    conversation_turns: parseConversationTurns(task.conversationTurns),
    conversation_state: parseConversationState(task.conversationState),
    cache_stats: parseCacheStats(task.localReuseStats || task.cacheStats),
    provider_cache_stats: parseProviderCacheStats(task.providerCacheStats),
    stage_metrics: parseStageMetrics(task.stageMetrics),
    event_stream_meta: parseEventStreamMeta(task.eventStreamMeta),
  };
}

function mapTaskFromDetail(data: any): AgentTask {
  return mapTaskFromApi(data);
}

function normalizeModificationItem(raw: any): ModificationItem | null {
  if (!raw || typeof raw !== "object") return null;
  const original = String(raw.original || "");
  const next = String(raw.new || raw.new_content || "");
  if (!original && !next) return null;
  return {
    section_name: String(raw.section_name || raw.sectionName || "修改段落"),
    section_index: toNumber(raw.section_index ?? raw.sectionIndex),
    original,
    new: next,
    reason: String(raw.reason || ""),
  };
}

function modificationKey(item: ModificationItem): string {
  return [
    item.section_index,
    item.section_name,
    item.original,
    item.new,
    item.reason,
  ].join("|");
}

function logKey(log: AgentLog): string {
  if (log.traceId && log.sequence) return `${log.traceId}|${log.sequence}`;
  return [log.timestamp, log.type, log.stage || "", log.agent || "", log.message].join("|");
}

function mergeAgentTask(current: AgentTask | null, next: AgentTask): AgentTask {
  if (!current || current.task_id !== next.task_id) return next;
  const mergedLogs = new Map<string, AgentLog>();
  [...current.logs, ...next.logs].forEach((log) => mergedLogs.set(logKey(log), log));
  return {
    ...current,
    ...next,
    logs: Array.from(mergedLogs.values()),
    optimized_resume_md: next.optimized_resume_md || current.optimized_resume_md,
    stream_preview_md: next.stream_preview_md || current.stream_preview_md,
    modification_diff_md: next.modification_diff_md || current.modification_diff_md,
    modification_log: next.modification_log.length ? next.modification_log : current.modification_log,
    conversation_turns: next.conversation_turns.length ? next.conversation_turns : current.conversation_turns,
    has_docx: next.has_docx || current.has_docx,
    event_stream_meta: next.event_stream_meta.snapshotBuildMs || next.event_stream_meta.pollIntervalMs
      ? next.event_stream_meta
      : current.event_stream_meta,
  };
}

function appendAgentLog(current: AgentTask | null, taskId: string, log: AgentLog): AgentTask | null {
  if (!current || current.task_id !== taskId) return current;
  if (current.logs.some((item) => logKey(item) === logKey(log))) return current;
  return {
    ...current,
    logs: [...current.logs, log],
  };
}

function appendModificationPatch(current: AgentTask | null, taskId: string, patch: unknown): AgentTask | null {
  if (!current || current.task_id !== taskId) return current;
  const item = normalizeModificationItem(patch);
  if (!item) return current;
  const seen = new Set(current.modification_log.map(modificationKey));
  if (seen.has(modificationKey(item))) return current;
  return {
    ...current,
    modification_log: [...current.modification_log, item],
  };
}

function formatTime(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function uniqueResumes(items: Resume[]): Resume[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item.id || seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function formatChatConfigLabel(config: ChatModelConfig): string {
  return config.name || `${config.provider} · ${config.modelId}`;
}

export function AgentResumePage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const { state: modelConfigState, activeChatConfig } = useModelConfigs();

  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [jdText, setJdText] = useState("");
  const [selectedConfigId, setSelectedConfigId] = useState("");

  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<AgentTask | null>(null);
  const [pollingTrigger, setPollingTrigger] = useState(0);

  const [isUploadingResume, setIsUploadingResume] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmittingAnswer, setIsSubmittingAnswer] = useState(false);
  const [isRetryingTask, setIsRetryingTask] = useState(false);
  const [loadingResumes, setLoadingResumes] = useState(true);
  const [loadingTasks, setLoadingTasks] = useState(true);

  const [uploadError, setUploadError] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [humanAnswerText, setHumanAnswerText] = useState("");
  const [answerType, setAnswerType] = useState<AnswerType>("evidence");
  const [evidenceScope, setEvidenceScope] = useState<EvidenceScope>("current_step");
  const [rememberAnswer, setRememberAnswer] = useState(true);
  const [copiedTarget, setCopiedTarget] = useState<CopyTarget | null>(null);
  const [resultTab, setResultTab] = useState<ResultTab>("resume");
  const [resultPanelOpen, setResultPanelOpen] = useState(true);
  const [conversationPanelOpen, setConversationPanelOpen] = useState(false);
  const [terminalFilter, setTerminalFilter] = useState<TerminalFilter>("all");
  const [runMode, setRunMode] = useState<AgentRunMode>("auto");
  const [executionMode, setExecutionMode] = useState<AgentExecutionMode>("pipeline");
  const [toolCallingMode, setToolCallingMode] = useState<AgentToolCallingMode>("json_action");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
  const [reviewStatus, setReviewStatus] = useState("准备投递");
  const [reviewNote, setReviewNote] = useState("");
  const [reviewSaved, setReviewSaved] = useState(false);
  const [offerScores, setOfferScores] = useState({
    compensation: 70,
    growth: 75,
    team: 70,
    location: 70,
    risk: 65,
  });

  const terminalEndRef = useRef<HTMLDivElement | null>(null);
  const processEndRef = useRef<HTMLDivElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const copyResetRef = useRef<number | null>(null);

  const chatConfigs = useMemo(
    () => modelConfigState.chatConfigs.filter((config) => config.enabled !== false),
    [modelConfigState.chatConfigs],
  );

  const selectedChatConfig = useMemo(
    () => chatConfigs.find((config) => config.id === selectedConfigId) || null,
    [chatConfigs, selectedConfigId],
  );

  const selectedResume = useMemo(
    () => resumes.find((resume) => resume.id === selectedResumeId) || null,
    [resumes, selectedResumeId],
  );

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      const response = await fetch("/api/agent/resume/tasks");
      if (response.ok) {
        const data = await response.json();
        setTasks((data.tasks || []).map(mapTaskFromApi));
      }
    } finally {
      setLoadingTasks(false);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setLoadingResumes(true);
    try {
      const resumeResponse = await fetch("/api/resumes");

      if (resumeResponse.ok) {
        const data = await resumeResponse.json();
        const nextResumes = data.resumes || [];
        setResumes(nextResumes);
        if (!selectedResumeId && nextResumes.length > 0) {
          setSelectedResumeId(nextResumes[0].id);
        }
      }
    } finally {
      setLoadingResumes(false);
      void loadTasks();
    }
  }, [loadTasks, selectedResumeId]);

  const fetchTaskDetail = useCallback(async (taskId: string) => {
    const response = await fetch(`/api/agent/resume/tasks/${encodeURIComponent(taskId)}`);
    if (!response.ok) return null;
    const data = await response.json();
    return mapTaskFromDetail(data);
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!chatConfigs.length) {
      if (selectedConfigId) setSelectedConfigId("");
      return;
    }
    if (selectedConfigId && chatConfigs.some((config) => config.id === selectedConfigId)) {
      return;
    }
    const activeId = activeChatConfig?.id;
    const fallbackConfig = activeId
      ? chatConfigs.find((config) => config.id === activeId)
      : null;
    setSelectedConfigId((fallbackConfig || chatConfigs[0]).id);
  }, [activeChatConfig?.id, chatConfigs, selectedConfigId]);

  useEffect(() => {
    if (!activeTaskId) return;

    let cancelled = false;
    let timerId: number | undefined;
    let source: EventSource | null = null;
    let pollingStarted = false;
    let finished = false;

    const finishTask = async (status?: AgentTask["status"]) => {
      if (finished || cancelled) return;
      finished = true;
      if (source) {
        source.close();
        source = null;
      }
      const task = await fetchTaskDetail(activeTaskId);
      if (!cancelled && task) {
        setActiveTask((current) => mergeAgentTask(current, task));
      }
      if (!cancelled && (!status || status !== "RUNNING")) {
        setActiveTaskId(null);
        void loadTasks();
      }
    };

    const tick = async () => {
      const task = await fetchTaskDetail(activeTaskId);
      if (cancelled || !task) return;
      setActiveTask((current) => mergeAgentTask(current, task));
      if (task.status === "COMPLETED" || task.status === "FAILED" || task.status === "WAITING_FOR_HUMAN") {
        void finishTask(task.status);
        return;
      }
      timerId = window.setTimeout(tick, 700);
    };

    const startPolling = () => {
      if (pollingStarted || cancelled) return;
      pollingStarted = true;
      void tick();
    };

    void fetchTaskDetail(activeTaskId).then((task) => {
      if (!cancelled && task) setActiveTask((current) => mergeAgentTask(current, task));
    });

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      source = new EventSource(`/api/agent/resume/tasks/${encodeURIComponent(activeTaskId)}/events`);
      source.addEventListener("connected", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
          const log: AgentLog = {
            timestamp: String(data.timestamp || new Date().toISOString()),
            type: "info",
            message: String(data.message || "事件流已连接，正在同步任务首包。"),
            detail: data,
            traceId: String(data.traceId || activeTaskId),
            stage: "stream_connected",
            agent: "SSE",
            status: "connected",
          };
          setActiveTask((current) => appendAgentLog(current, activeTaskId, log));
        } catch {
          // The first snapshot will repair the visible state.
        }
      });
      source.addEventListener("agent_log", (event) => {
        if (cancelled) return;
        try {
          const log = JSON.parse((event as MessageEvent).data) as AgentLog;
          setActiveTask((current) => appendAgentLog(current, activeTaskId, log));
        } catch {
          // Ignore malformed stream chunks and let the next snapshot correct the state.
        }
      });
      source.addEventListener("modification_patch", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
          setActiveTask((current) => appendModificationPatch(current, activeTaskId, data.patch));
        } catch {
          // Snapshot/detail polling will still recover the modification log.
        }
      });
      source.addEventListener("snapshot", (event) => {
        if (cancelled) return;
        try {
          const task = mapTaskFromApi(JSON.parse((event as MessageEvent).data));
          setActiveTask((current) => mergeAgentTask(current, task));
          if (task.status === "COMPLETED" || task.status === "FAILED" || task.status === "WAITING_FOR_HUMAN") {
            void finishTask(task.status);
          }
        } catch {
          startPolling();
        }
      });
      source.addEventListener("retry_available", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
          const log: AgentLog = {
            timestamp: String(data.timestamp || new Date().toISOString()),
            type: "error",
            message: data.failedToolName
              ? `失败点可重试：${String(data.failedToolName)}`
              : "失败点可重试",
            detail: data,
            traceId: String(data.traceId || activeTaskId),
            stage: String(data.stage || "retry"),
            agent: String(data.agent || "Retry"),
            status: String(data.status || "available"),
            retryCount: toNumber(data.retryCount),
          };
          setActiveTask((current) => appendAgentLog(current, activeTaskId, log));
        } catch {
          // Snapshot polling will still recover the retry state.
        }
      });
      source.addEventListener("done", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((event as MessageEvent).data) as { status?: AgentTask["status"] };
          void finishTask(data.status);
        } catch {
          void finishTask();
        }
      });
      source.onerror = () => {
        if (cancelled || finished) return;
        source?.close();
        source = null;
        startPolling();
      };
    }

    return () => {
      cancelled = true;
      source?.close();
      if (timerId) window.clearTimeout(timerId);
    };
  }, [activeTaskId, fetchTaskDetail, loadTasks, pollingTrigger]);

  useEffect(() => {
    processEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeTask?.logs]);

  useEffect(() => () => {
    if (copyResetRef.current !== null) {
      window.clearTimeout(copyResetRef.current);
    }
  }, []);

  useEffect(() => {
    if (!activeTask) return;
    const key = `internpath-agent-review-${activeTask.task_id}`;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) {
        const parsed = JSON.parse(raw);
        setReviewStatus(parsed.status || "准备投递");
        setReviewNote(parsed.note || "");
      } else {
        setReviewStatus("准备投递");
        setReviewNote("");
      }
      setReviewSaved(false);
    } catch {
      setReviewStatus("准备投递");
      setReviewNote("");
      setReviewSaved(false);
    }
  }, [activeTask]);

  useEffect(() => {
    setResultPanelOpen(true);
    setConversationPanelOpen(activeTask?.status === "WAITING_FOR_HUMAN");
  }, [activeTask?.task_id, activeTask?.status]);

  const handleResumeUpload = async (file: File | null) => {
    if (!file) return;
    const validationError = validateResumeFile(file);
    if (validationError) {
      setUploadError(validationError);
      setUploadMessage("");
      return;
    }

    setIsUploadingResume(true);
    setUploadError("");
    setUploadMessage("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/resumes/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response, "上传解析失败"));
      }

      const payload = await response.json();
      const resumeFile = payload.resumeFile || payload.parsedResume?.file;
      if (!resumeFile?.id) {
        throw new Error("解析服务返回结果格式异常");
      }

      setResumes((current) => uniqueResumes([resumeFile, ...current]));
      setSelectedResumeId(resumeFile.id);
      setUploadMessage(`已选择 ${resumeFile.name}`);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "上传解析失败");
    } finally {
      setIsUploadingResume(false);
    }
  };

  const handleStartOptimize = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedResumeId) {
      setUploadError("请先上传或选择一份简历");
      return;
    }
    if (!jdText.trim()) {
      setUploadError("请粘贴目标岗位 JD");
      return;
    }
    if (!selectedConfigId) {
      setUploadError("请先在设置中配置并选择一个可用的大语言模型");
      return;
    }

    setIsSubmitting(true);
    setUploadError("");
    try {
      const submitToolCallingMode = executionMode === "agentic" ? toolCallingMode : "auto";
      const response = await fetch("/api/agent/resume/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: selectedResumeId,
          jd_text: jdText.trim(),
          config_id: selectedConfigId || null,
          is_co_pilot: runMode === "copilot",
          executionMode,
          toolCallingMode: submitToolCallingMode,
        }),
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response, "启动简历优化失败"));
      }

      const data = await response.json();
      if (data.cacheHit) {
        setUploadMessage(data.message || "已复用相同输入的历史任务");
        const cachedTask = data.task ? mapTaskFromApi(data.task) : await fetchTaskDetail(data.taskId);
        if (cachedTask) {
          setActiveTask(cachedTask);
          setResultTab("resume");
          if (cachedTask.status === "PENDING" || cachedTask.status === "RUNNING" || cachedTask.status === "WAITING_FOR_HUMAN") {
            setActiveTaskId(cachedTask.task_id);
          }
        }
        void loadTasks();
        return;
      }

      const newTask: AgentTask = data.task
        ? mapTaskFromApi(data.task)
        : {
          task_id: data.taskId,
          status: "PENDING",
          resume_id: selectedResumeId,
          original_resume_name: selectedResume?.name || "resume.pdf",
          jd_text: jdText.trim(),
          logs: [],
          optimized_resume_md: "",
          stream_preview_md: "",
          error_message: "",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          modification_diff_md: "",
          has_docx: false,
          modification_log: [],
          execution_plan: "",
          execution_mode: normalizeAgentExecutionMode(data.executionMode || executionMode),
          tool_calling_mode: normalizeAgentToolCallingMode(data.toolCallingMode || submitToolCallingMode),
          conversation_turns: [],
          conversation_state: { summary: "", globalPreferences: [], factLedger: [], updatedAt: "" },
          cache_stats: emptyCacheStats(),
          provider_cache_stats: emptyProviderCacheStats(),
          stage_metrics: [],
          event_stream_meta: { snapshotBuildMs: 0, artifactMode: "", pollIntervalMs: 0 },
        };
      setActiveTask(newTask);
      setActiveTaskId(newTask.task_id);
      setResultTab("resume");
      void loadTasks();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "请求失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSelectTask = async (task: AgentTask) => {
    setActiveTask(task);
    setActiveTaskId(null);
    setResultTab("resume");
    const detail = await fetchTaskDetail(task.task_id);
    if (detail) setActiveTask(detail);
  };

  const handleRetryTask = async () => {
    if (!activeTask || activeTask.status !== "FAILED") return;
    setIsRetryingTask(true);
    setUploadError("");
    try {
      const response = await fetch(`/api/agent/resume/tasks/${encodeURIComponent(activeTask.task_id)}/retry`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await parseApiError(response, "重试失败"));
      }
      const data = await response.json().catch(() => ({}));
      const retriedTask = await fetchTaskDetail(activeTask.task_id);
      if (retriedTask) {
        setActiveTask(retriedTask);
      }
      setActiveTaskId(activeTask.task_id);
      setResultTab("resume");
      setUploadMessage(data.message || "已从失败点重试");
      void loadTasks();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "重试失败");
    } finally {
      setIsRetryingTask(false);
    }
  };

  const handleDeleteTask = async (taskId: string, event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!window.confirm("确定删除这条优化记录？")) return;
    const response = await fetch(`/api/agent/resume/tasks/${encodeURIComponent(taskId)}`, {
      method: "DELETE",
    });
    if (response.ok) {
      if (activeTask?.task_id === taskId) setActiveTask(null);
      void loadTasks();
    }
  };

  const handleSubmitAnswer = async (
    answerText: string,
    remember = rememberAnswer,
    nextAnswerType: AnswerType | "skip" = answerType,
  ) => {
    if (!activeTask) return;
    setIsSubmittingAnswer(true);
    try {
      const response = await fetch(`/api/agent/resume/tasks/${encodeURIComponent(activeTask.task_id)}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answer_text: answerText,
          answer_type: nextAnswerType,
          remember,
          evidence_scope: evidenceScope,
        }),
      });
      if (!response.ok) {
        throw new Error(await parseApiError(response, "提交回答失败"));
      }
      const data = await response.json().catch(() => ({}));
      setHumanAnswerText("");
      setAnswerType("evidence");
      setEvidenceScope("current_step");
      setRememberAnswer(true);
      setPollingTrigger((value) => value + 1);
      const refreshedTask = await fetchTaskDetail(activeTask.task_id);
      if (refreshedTask) {
        setActiveTask(refreshedTask);
      }
      if (data.status === "RUNNING" || activeTask.status === "PENDING" || activeTask.status === "RUNNING" || activeTask.status === "WAITING_FOR_HUMAN") {
        setActiveTaskId(activeTask.task_id);
      }
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "提交回答失败");
    } finally {
      setIsSubmittingAnswer(false);
    }
  };

  const markCopied = (target: CopyTarget) => {
    setCopiedTarget(target);
    if (copyResetRef.current !== null) {
      window.clearTimeout(copyResetRef.current);
    }
    copyResetRef.current = window.setTimeout(() => setCopiedTarget(null), 1600);
  };

  const handleCopyMarkdown = async () => {
    if (!activeTask?.optimized_resume_md) return;
    await navigator.clipboard.writeText(activeTask.optimized_resume_md);
    markCopied("resume");
  };

  const handleCopyText = async (text: string) => {
    await navigator.clipboard.writeText(text);
    markCopied("text");
  };

  const handleCopyActionPack = async () => {
    if (!actionPackMarkdown) return;
    await navigator.clipboard.writeText(actionPackMarkdown);
    markCopied("action-pack");
  };

  const handleDownloadActionPack = () => {
    if (!activeTask || !actionPackMarkdown) return;
    const blob = new Blob([actionPackMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `InternPath_action_pack_${activeTask.task_id}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const handleSaveReview = () => {
    if (!activeTask) return;
    const key = `internpath-agent-review-${activeTask.task_id}`;
    window.localStorage.setItem(key, JSON.stringify({
      status: reviewStatus,
      note: reviewNote,
      updatedAt: new Date().toISOString(),
    }));
    setReviewSaved(true);
    window.setTimeout(() => setReviewSaved(false), 1600);
  };

  const filteredLogs = useMemo(() => {
    const logs = activeTask?.logs || [];
    return logs.filter((log) => {
      if (terminalFilter === "thought") return log.type === "thought";
      if (terminalFilter === "tool") return log.type === "tool_call" || log.type === "tool_response";
      return true;
    });
  }, [activeTask?.logs, terminalFilter]);

  const conversationTurns = useMemo(() => {
    return [...(activeTask?.conversation_turns || [])].sort((a, b) => {
      const left = new Date(a.createdAt).getTime();
      const right = new Date(b.createdAt).getTime();
      return (Number.isFinite(left) ? left : 0) - (Number.isFinite(right) ? right : 0);
    });
  }, [activeTask?.conversation_turns]);

  const completedSteps = activeTask
    ? [
      activeTask.logs.some((log) => log.message.includes("执行计划")),
      activeTask.logs.some((log) => log.message.includes("防幻觉")),
      activeTask.logs.some((log) => log.message.includes("DOCX")),
      activeTask.status === "COMPLETED",
    ].filter(Boolean).length
    : 0;
  const activeLocalReuseStats = activeTask?.cache_stats || emptyCacheStats();
  const localReuseTotal = activeLocalReuseStats.hits + activeLocalReuseStats.misses;
  const localReuseHitRate = localReuseTotal > 0 ? Math.round((activeLocalReuseStats.hits / localReuseTotal) * 100) : activeLocalReuseStats.hitRate;
  const recentLocalReuseItems = activeLocalReuseStats.items.slice(-6).reverse();
  const providerCacheStats = activeTask?.provider_cache_stats || emptyProviderCacheStats();
  const providerCacheChecks = providerCacheStats.checks || providerCacheStats.hits + providerCacheStats.misses;
  const providerCacheHitRate = providerCacheChecks > 0 ? Math.round((providerCacheStats.hits / providerCacheChecks) * 100) : providerCacheStats.hitRate;
  const recentProviderCacheItems = providerCacheStats.items.slice(-4).reverse();
  const processLogs = useMemo(() => buildVisibleProcessLogs(activeTask?.logs || []), [activeTask?.logs]);
  const agentProgress = useMemo(() => buildAgentProgress(activeTask), [activeTask]);
  const lastFailureLogIndex = useMemo(() => {
    if (activeTask?.status !== "FAILED") return -1;
    for (let index = processLogs.length - 1; index >= 0; index -= 1) {
      if (processLogs[index].type === "error") return index;
    }
    return processLogs.length - 1;
  }, [activeTask?.status, processLogs]);
  const visibleResumeMd = activeTask
    ? activeTask.status === "COMPLETED"
      ? activeTask.optimized_resume_md
      : activeTask.status === "FAILED"
        ? ""
        : activeTask.stream_preview_md || activeTask.optimized_resume_md
    : "";
  const liveEditSummary = useMemo(() => {
    const logs = [...(activeTask?.logs || [])].reverse();
    for (const log of logs) {
      const summary = getLiveEditSummary(log);
      if (summary) return summary;
    }
    return null;
  }, [activeTask?.logs]);
  const selectedSlashCommand = slashCommands.find(
    (command) => command.answerType === answerType && command.evidenceScope === evidenceScope,
  ) || slashCommands[0];
  const stageMetrics = useMemo(
    () => [...(activeTask?.stage_metrics || [])].sort((a, b) => b.durationMs - a.durationMs),
    [activeTask?.stage_metrics],
  );
  const totalStageDurationMs = stageMetrics.reduce((sum, item) => sum + item.durationMs, 0);
  const totalModelCalls = stageMetrics.reduce((sum, item) => sum + item.modelCalls, 0);
  const totalSavedModelCalls = stageMetrics.reduce((sum, item) => sum + item.savedModelCalls, 0);
  const factLedger = useMemo(
    () => buildFactLedger(activeTask?.modification_log || [], activeTask?.jd_text || ""),
    [activeTask?.modification_log, activeTask?.jd_text],
  );
  const jdRadar = useMemo(
    () => buildJdRadar(activeTask?.jd_text || "", activeTask?.optimized_resume_md || ""),
    [activeTask?.jd_text, activeTask?.optimized_resume_md],
  );
  const resumeVariants = useMemo(
    () => buildResumeVariants(activeTask?.optimized_resume_md || "", jdRadar),
    [activeTask?.optimized_resume_md, jdRadar],
  );
  const interviewQuestions = useMemo(
    () => buildInterviewQuestions(activeTask?.modification_log || [], jdRadar),
    [activeTask?.modification_log, jdRadar],
  );
  const applicationSnippets = useMemo(
    () => buildApplicationSnippets(activeTask?.optimized_resume_md || "", activeTask?.jd_text || ""),
    [activeTask?.optimized_resume_md, activeTask?.jd_text],
  );
  const offerDecision = useMemo(() => evaluateOfferDecision(offerScores), [offerScores]);
  const actionPackMarkdown = useMemo(() => {
    if (!activeTask) return "";
    return buildActionPackMarkdown({
      taskId: activeTask.task_id,
      resumeName: activeTask.original_resume_name,
      updatedAt: activeTask.updated_at,
      jdText: activeTask.jd_text,
      optimizedResumeMd: activeTask.optimized_resume_md,
      factLedger,
      jdRadar,
      resumeVariants,
      interviewQuestions,
      applicationSnippets,
      review: {
        status: reviewStatus,
        note: reviewNote,
      },
      offerDecision,
      cacheSummary: {
        hitRate: localReuseHitRate,
        hits: activeLocalReuseStats.hits,
        misses: activeLocalReuseStats.misses,
        savedModelCalls: activeLocalReuseStats.savedModelCalls,
      },
    });
  }, [
    activeTask,
    factLedger,
    jdRadar,
    resumeVariants,
    interviewQuestions,
    applicationSnippets,
    reviewStatus,
    reviewNote,
    offerDecision,
    localReuseHitRate,
    activeLocalReuseStats.hits,
    activeLocalReuseStats.misses,
    activeLocalReuseStats.savedModelCalls,
  ]);

  const waitingForHuman = activeTask?.status === "WAITING_FOR_HUMAN";
  const dialogueTitle = waitingForHuman ? "需要确认" : "继续这个任务";
  const dialogueHelper = waitingForHuman
    ? "LLM 已读到无法确认的事实缺口。"
    : "追问结果、补充事实或记录偏好。";
  const dialoguePrompt = waitingForHuman
    ? activeTask?.pending_question || "请补充可确认的项目细节，或选择无补充继续。"
    : "继续追问这次优化，或补充后续投递要记住的真实信息。";

  return (
    <div className="agent-page">
      <div className="agent-workbench">
        <aside className="agent-side">
          <section className="agent-panel agent-history-panel">
            <div className="agent-panel-title">
              <span>优化记录</span>
              <button
                type="button"
                className="agent-new-thread-button"
                onClick={() => {
                  setActiveTask(null);
                  setActiveTaskId(null);
                }}
              >
                新任务
              </button>
            </div>
            <small className="agent-thread-count">{loadingTasks ? "读取中" : `${tasks.length} 条记录`}</small>
            <div className="agent-task-list">
              {tasks.length === 0 && !loadingTasks && (
                <div className="agent-empty-row">暂无记录</div>
              )}
              {tasks.map((task) => (
                <div
                  key={task.task_id}
                  role="button"
                  tabIndex={0}
                  className={`agent-task-item ${activeTask?.task_id === task.task_id ? "active" : ""}`}
                  onClick={() => void handleSelectTask(task)}
                  onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void handleSelectTask(task);
                    }
                  }}
                >
                  <span>
                    <strong>{task.original_resume_name || "resume"}</strong>
                    <small>{formatTime(task.created_at)}</small>
                  </span>
                  <em className={`agent-status is-${task.status.toLowerCase()}`}>{statusLabels[task.status]}</em>
                  <button
                    type="button"
                    className="agent-task-delete"
                    onClick={(event) => void handleDeleteTask(task.task_id, event)}
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          </section>
        </aside>

        <main className="agent-main">
          <header className="agent-thread-header">
            <div>
              <span>InternPath</span>
              <h2>简历定向优化</h2>
              <p>{activeTask ? activeTask.original_resume_name : "选择简历，粘贴 JD，然后让系统先读完再决定是否需要补充。"}</p>
            </div>
            {activeTask && (
              <div className="agent-thread-tools">
                <button
                  type="button"
                  className="agent-summary-button"
                  aria-expanded={summaryOpen}
                  onClick={() => setSummaryOpen((value) => !value)}
                >
                  概要
                  <strong>{providerCacheChecks > 0 ? `${providerCacheHitRate}%` : `${localReuseHitRate}%`}</strong>
                </button>
                {summaryOpen && (
                  <div className="agent-summary-popover">
                    <div className="agent-summary-grid">
                      <div>
                        <strong>{statusLabels[activeTask.status]}</strong>
                        <span>当前状态</span>
                      </div>
                      <div>
                        <strong>{completedSteps}/4</strong>
                        <span>主流程</span>
                      </div>
                      <div>
                        <strong>{providerCacheChecks > 0 ? `${providerCacheHitRate}%` : "未上报"}</strong>
                        <span>大模型缓存</span>
                      </div>
                      <div>
                        <strong>{providerCacheStats.cachedTokens}</strong>
                        <span>缓存 tokens</span>
                      </div>
                      <div>
                        <strong>{localReuseHitRate}%</strong>
                        <span>本地复用率</span>
                      </div>
                      <div>
                        <strong>{activeLocalReuseStats.savedModelCalls}</strong>
                        <span>本地节省生成</span>
                      </div>
                      <div>
                        <strong>{totalModelCalls}</strong>
                        <span>实际生成</span>
                      </div>
                    </div>
                    {recentProviderCacheItems.length > 0 && (
                      <div className="agent-cache-events">
                        {recentProviderCacheItems.map((item, index) => (
                          <em key={`${item.stage}-${item.modelId}-${item.timestamp}-${index}`} className={item.hit ? "hit" : "miss"}>
                            <span>
                              {item.endpointMode ? ` ${item.endpointMode === "responses" ? "Responses" : item.endpointMode}${item.stream ? " stream=true" : item.stream === false ? " stream=false" : ""}` : ""}
                              {item.promptCacheDisabledReason ? " Prompt Cache disabled" : ""}
                            </span>
                            {item.hit ? "大模型缓存命中" : "大模型缓存未命中"} {item.cachedTokens} tokens
                          </em>
                        ))}
                      </div>
                    )}
                    {recentLocalReuseItems.length > 0 && (
                      <div className="agent-cache-events">
                        {recentLocalReuseItems.map((item, index) => (
                          <em key={`${item.namespace}-${item.label}-${index}`} className={item.hit ? "hit" : "miss"}>
                            {item.hit ? "本地已复用" : "本地新生成"} {friendlyProcessLabel(item.label)}
                          </em>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </header>

          {activeTask ? (
            <>
              <div className="agent-live-layout">
                <section className="agent-live-primary">
              <section className="agent-panel agent-status-panel">
                <div>
                  <span className={`agent-status is-${activeTask.status.toLowerCase()}`}>{statusLabels[activeTask.status]}</span>
                  <h2>{activeTask.original_resume_name}</h2>
                  <div className="agent-mode-badges">
                    <em>{executionModeLabels[activeTask.execution_mode]}</em>
                    <em>{toolCallingModeLabels[activeTask.tool_calling_mode]}</em>
                  </div>
                  <p>{activeTask.status === "COMPLETED" ? "投递版本已生成" : "正在按真实经历处理简历"}</p>
                </div>
                <div className={`agent-progress agent-live-progress is-${agentProgress.activeStage}`} aria-live="polite">
                  <div className="agent-progress-meter">
                    <strong>{agentProgress.percent}%</strong>
                    <span>{agentProgress.title}</span>
                  </div>
                  <div className="agent-progress-track" role="progressbar" aria-valuenow={agentProgress.percent} aria-valuemin={0} aria-valuemax={100}>
                    <i style={{ width: `${agentProgress.percent}%` }} />
                  </div>
                  <p>{agentProgress.currentAction}</p>
                  <small>{agentProgress.detail}</small>
                  {agentProgress.recentActivities.length > 0 && (
                    <div className="agent-progress-activity">
                      {agentProgress.recentActivities.map((activity, index) => (
                        <em key={`${activity}-${index}`}>{activity}</em>
                      ))}
                    </div>
                  )}
                </div>
                {activeTask.status === "FAILED" && (
                  <button
                    type="button"
                    className="agent-retry-button"
                    onClick={() => void handleRetryTask()}
                    disabled={isRetryingTask}
                  >
                    {isRetryingTask ? "正在重试..." : "从失败点重试"}
                  </button>
                )}
              </section>

              {waitingForHuman && (
              <section className="agent-panel agent-human-panel is-waiting">
                <div className="agent-dialogue-head">
                  <strong>{dialogueTitle}</strong>
                  <span>{dialogueHelper}</span>
                </div>
                <p>{dialoguePrompt}</p>
              </section>
              )}

              <section className="agent-panel agent-process-stream" aria-label="Agent 执行过程">
                <div className="agent-process-head">
                  <strong>过程</strong>
                  <span>{activeTask.status === "RUNNING" ? "实时流式更新" : "最近步骤"}</span>
                </div>
                <div className="agent-process-list">
                  {processLogs.length === 0 && (
                    <div className="agent-process-line is-info">
                      <span>正在创建任务首包，准备同步本地预热和队列状态。</span>
                    </div>
                  )}
                  {processLogs.map((log, index) => (
                    <AgentProcessLogLine
                      key={`${log.timestamp}-${index}`}
                      log={log}
                      isFailurePoint={index === lastFailureLogIndex}
                      isRetryingTask={isRetryingTask}
                      onRetry={() => void handleRetryTask()}
                    />
                  ))}
                  <div ref={processEndRef} />
                </div>
              </section>

              <section className={`agent-panel agent-followup-composer ${waitingForHuman ? "is-waiting" : ""}`}>
                <div className="agent-composer-title">
                  <strong>{dialogueTitle}</strong>
                  <span>{dialogueHelper}</span>
                </div>
                <textarea
                  ref={composerInputRef}
                  value={humanAnswerText}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setHumanAnswerText(nextValue);
                    setSlashOpen(/(^|\s)\/$/.test(nextValue));
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setSlashOpen(false);
                  }}
                  placeholder={waitingForHuman ? `${answerTypePlaceholders[answerType]} 输入 / 切换功能` : `${dialoguePrompt} 输入 / 选择功能`}
                  disabled={isSubmittingAnswer}
                />
                {slashOpen && (
                  <div className="agent-slash-menu">
                    {slashCommands.map((command) => (
                      <button
                        key={command.id}
                        type="button"
                        onClick={() => {
                          setAnswerType(command.answerType);
                          setEvidenceScope(command.evidenceScope);
                          setRememberAnswer(command.remember);
                          setSlashOpen(false);
                          setHumanAnswerText((current) => current.replace(/(^|\s)\/$/, "$1").trimStart());
                          window.setTimeout(() => composerInputRef.current?.focus(), 0);
                        }}
                      >
                        <strong>/{command.label}</strong>
                        <span>{command.hint}</span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="agent-human-actions">
                  <span className="agent-selected-command">
                    /{selectedSlashCommand.label} · {evidenceScopeLabels[evidenceScope]} · {rememberAnswer ? "会记住" : "仅本次"}
                  </span>
                  {waitingForHuman && (
                    <button type="button" onClick={() => void handleSubmitAnswer("无补充，请保持原始事实继续。", false, "skip")} disabled={isSubmittingAnswer}>
                      无补充
                    </button>
                  )}
                  <button
                    type="button"
                    className="agent-primary-button compact"
                    onClick={() => {
                      if (!humanAnswerText.trim()) {
                        setUploadError(waitingForHuman ? "请填写补充内容，或选择无补充" : "请先输入要继续讨论的内容");
                        return;
                      }
                      void handleSubmitAnswer(humanAnswerText.trim(), rememberAnswer, answerType);
                    }}
                    disabled={isSubmittingAnswer}
                  >
                    {waitingForHuman ? "提交并继续" : "发送"}
                  </button>
                </div>
              </section>
              </section>

              <aside className="agent-right-rail">

              {conversationTurns.length > 0 && (
                <details
                  className="agent-panel agent-conversation agent-right-section"
                  open={conversationPanelOpen}
                  onToggle={(event) => setConversationPanelOpen(event.currentTarget.open)}
                >
                  <summary>确认记录</summary>
                  <div className="agent-conversation-list">
                    {conversationTurns.map((turn, index) => (
                      <article key={turn.id || `${turn.role}-${turn.createdAt}-${index}`} className={`agent-turn is-${turn.role}`}>
                        <div>
                          <strong>{turn.role === "assistant" ? "工作台" : "用户"}</strong>
                          <span>步骤 {turn.stepIndex ?? "-"}</span>
                          {turn.answerType && <em>{answerTypeLabels[turn.answerType as AnswerType] || turn.answerType}</em>}
                          {turn.consumedAt && <small>已用于生成 {formatTime(turn.consumedAt)}</small>}
                          {!turn.consumedAt && turn.role === "user" && <small>待处理</small>}
                        </div>
                        <p>{turn.content}</p>
                        <time>{formatTime(turn.createdAt)}</time>
                      </article>
                    ))}
                  </div>
                </details>
              )}

              <details
                className="agent-panel agent-result-panel agent-right-section"
                open={resultPanelOpen}
                onToggle={(event) => setResultPanelOpen(event.currentTarget.open)}
              >
                <summary className="agent-right-summary">
                  <span>优化稿 / 修改对照</span>
                  <small>可收起</small>
                </summary>
                <div className="agent-result-toolbar">
                  <div className="agent-tabs" role="tablist">
                    <button type="button" className={resultTab !== "diff" ? "active" : ""} onClick={() => setResultTab("resume")}>优化稿</button>
                    <button type="button" className={resultTab === "diff" ? "active" : ""} onClick={() => setResultTab("diff")}>修改对照</button>
                  </div>

                  {activeTask.status === "COMPLETED" && (
                    <div className="agent-actions">
                      <button type="button" onClick={() => void handleCopyMarkdown()}>{copiedTarget === "resume" ? "已复制" : "复制 MD"}</button>
                      <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download`}>MD</a>
                      {activeTask.has_docx && <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download?format=docx`}>DOCX</a>}
                      {activeTask.has_docx && <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download?format=pdf`}>PDF</a>}
                    </div>
                  )}
                </div>

                {resultTab !== "diff" && (
                  <>
                    {liveEditSummary && (
                      <div className={`agent-live-edit is-${liveEditSummary.status}`}>
                        <strong>{liveEditSummary.title}</strong>
                        <span>{liveEditSummary.detail || "等待工具返回修改片段"}</span>
                      </div>
                    )}
                    <pre className="agent-resume-preview">
                      {visibleResumeMd || (activeTask.status === "FAILED" ? activeTask.error_message : "等待生成结果...")}
                    </pre>
                  </>
                )}

                {resultTab === "diff" && (
                  activeTask.modification_log.length > 0
                    ? <ResumeDiffView modificationLog={activeTask.modification_log} optimizedResumeMd={activeTask.optimized_resume_md} />
                    : <div className="agent-empty-row">暂无修改对照</div>
                )}
              </details>

              <details className="agent-panel agent-secondary-panel agent-right-section">
                <summary>
                  <span>辅助工作区</span>
                  <small>行动台、运行明细和过程记录默认收起，不影响生成主线。</small>
                </summary>
                <div className="agent-secondary-options" role="group" aria-label="辅助工作区">
                  <button type="button" className={resultTab === "insights" ? "active" : ""} onClick={() => setResultTab("insights")}>
                    <strong>行动台</strong>
                    <span>投递动作、网申文案、面试追问和复盘记录。</span>
                  </button>
                  <button type="button" className={resultTab === "diagnostics" ? "active" : ""} onClick={() => setResultTab("diagnostics")}>
                    <strong>运行明细</strong>
                    <span>查看耗时、大模型缓存、本地复用和每步状态。</span>
                  </button>
                  <button type="button" className={resultTab === "logs" ? "active" : ""} onClick={() => setResultTab("logs")}>
                    <strong>过程记录</strong>
                    <span>排查问题时再看模型调用、工具执行和详细日志。</span>
                  </button>
                </div>
                {resultTab !== "insights" && resultTab !== "diagnostics" && resultTab !== "logs" && (
                  <div className="agent-empty-row">展开后选择一个辅助视图查看；日常只看优化稿和修改对照即可。</div>
                )}

                {resultTab === "insights" && (
                  <div className="agent-insights">
                    {activeTask.status === "COMPLETED" && (
                      <section className="agent-insight-band agent-action-pack-bar">
                        <div>
                          <strong>行动包</strong>
                          <span>把投递动作、网申文案、面试追问和复盘信息打包成 Markdown。</span>
                        </div>
                        <div className="agent-actions">
                          <button type="button" onClick={() => void handleCopyActionPack()}>{copiedTarget === "action-pack" ? "已复制" : "复制行动包"}</button>
                          <button type="button" onClick={handleDownloadActionPack}>下载行动包</button>
                        </div>
                      </section>
                    )}
                    <section className="agent-insight-band">
                      <div className="agent-insight-title">
                        <span>事实核对</span>
                        <strong>{factLedger.filter((item) => item.status === "verified").length}/{factLedger.length || 0} 已验证</strong>
                      </div>
                      <div className="agent-fact-ledger">
                        {factLedger.length === 0 && <div className="agent-empty-row">暂无修改记录</div>}
                        {factLedger.map((item) => (
                          <article key={`${item.sectionIndex}-${item.sectionName}`} className={`agent-fact-card is-${item.status}`}>
                            <div>
                              <strong>{item.sectionName}</strong>
                              <span>{item.summary}</span>
                            </div>
                            <div className="agent-fact-meta">
                              <em>{factStatusLabels[item.status]}</em>
                              <em>{factSourceLabels[item.source]}</em>
                            </div>
                            {item.addedFacts.length > 0 && (
                              <p>新增硬事实：{item.addedFacts.slice(0, 6).join("、")}</p>
                            )}
                            <small>{item.reason}</small>
                          </article>
                        ))}
                      </div>
                    </section>

                    <section className="agent-insight-band">
                      <div className="agent-insight-title">
                        <span>岗位关键词覆盖</span>
                        <strong>{jdRadar.score}%</strong>
                      </div>
                      <div className="agent-radar-bar">
                        <span style={{ width: `${jdRadar.score}%` }} />
                      </div>
                      <div className="agent-keyword-cloud">
                        {jdRadar.matched.slice(0, 16).map((item) => <em key={`hit-${item.keyword}`} className="hit">{item.keyword}</em>)}
                        {jdRadar.missing.slice(0, 12).map((item) => <em key={`miss-${item.keyword}`} className="miss">{item.keyword}</em>)}
                      </div>
                    </section>

                    <section className="agent-insight-grid">
                      <div className="agent-insight-band">
                        <div className="agent-insight-title">
                          <span>简历版本建议</span>
                          <strong>{resumeVariants.length} 个版本</strong>
                        </div>
                        <div className="agent-variant-list">
                          {resumeVariants.map((variant) => (
                            <article key={variant.name}>
                              <strong>{variant.name}</strong>
                              <span>{variant.focus}</span>
                              <pre>{variant.preview}</pre>
                              <button type="button" onClick={() => void handleCopyText(variant.preview)}>复制</button>
                            </article>
                          ))}
                        </div>
                      </div>

                      <div className="agent-insight-band">
                        <div className="agent-insight-title">
                          <span>面试追问</span>
                          <strong>{interviewQuestions.length} 题</strong>
                        </div>
                        <ol className="agent-question-list">
                          {interviewQuestions.map((item, index) => (
                            <li key={`${item.sectionName}-${index}`}>
                              <span>{item.sectionName}</span>
                              <p>{item.question}</p>
                            </li>
                          ))}
                        </ol>
                      </div>
                    </section>

                    <section className="agent-insight-grid">
                      <div className="agent-insight-band">
                        <div className="agent-insight-title">
                          <span>网申填表</span>
                          <strong>{applicationSnippets.length} 段</strong>
                        </div>
                        <div className="agent-snippet-list">
                          {applicationSnippets.map((snippet) => (
                            <article key={snippet.label}>
                              <strong>{snippet.label}</strong>
                              <p>{snippet.text}</p>
                              <button type="button" onClick={() => void handleCopyText(snippet.text)}>复制</button>
                            </article>
                          ))}
                        </div>
                      </div>

                      <div className="agent-insight-band">
                        <div className="agent-insight-title">
                          <span>投递复盘记忆</span>
                          <strong>{reviewSaved ? "已保存" : reviewStatus}</strong>
                        </div>
                        <div className="agent-review-box">
                          <select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value)}>
                            <option>准备投递</option>
                            <option>已投递</option>
                            <option>已约面</option>
                            <option>已拒绝</option>
                            <option>已 Offer</option>
                          </select>
                          <textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="记录投递渠道、反馈、下次要调整的表达" />
                          <button type="button" onClick={handleSaveReview}>保存复盘</button>
                        </div>
                      </div>
                    </section>

                    <section className="agent-insight-band">
                      <div className="agent-insight-title">
                          <span>Offer 取舍</span>
                          <strong>{offerDecision.score} · {offerDecision.verdict}</strong>
                      </div>
                      <div className="agent-offer-grid">
                        {Object.entries(offerScores).map(([key, value]) => (
                          <label key={key}>
                            <span>{offerScoreLabels[key as keyof typeof offerScoreLabels]}</span>
                            <input
                              type="range"
                              min="0"
                              max="100"
                              value={value}
                              onChange={(event) => setOfferScores((current) => ({
                                ...current,
                                [key]: Number(event.target.value),
                              }))}
                            />
                            <strong>{value}</strong>
                          </label>
                        ))}
                      </div>
                      {offerDecision.risks.length > 0 && (
                        <p className="agent-offer-risk">需确认：{offerDecision.risks.map((key) => offerScoreLabels[key as keyof typeof offerScoreLabels]).join("、")}</p>
                      )}
                    </section>
                  </div>
                )}

                {resultTab === "diagnostics" && (
                  <div className="agent-diagnostics">
                    <section className="agent-diagnostic-summary">
                      <div>
                        <strong>{totalStageDurationMs}ms</strong>
                        <span>累计耗时</span>
                      </div>
                      <div>
                        <strong>{totalModelCalls}</strong>
                        <span>生成次数</span>
                      </div>
                      <div>
                        <strong>{providerCacheStats.cachedTokens}</strong>
                        <span>大模型缓存 tokens</span>
                      </div>
                      <div>
                        <strong>{totalSavedModelCalls || activeLocalReuseStats.savedModelCalls}</strong>
                        <span>本地复用节省</span>
                      </div>
                      <div>
                        <strong>{activeLocalReuseStats.hits}/{activeLocalReuseStats.misses}</strong>
                        <span>本地复用/新算</span>
                      </div>
                      <div>
                        <strong>{activeTask.event_stream_meta.snapshotBuildMs}ms</strong>
                        <span>SSE 构建</span>
                      </div>
                      <div>
                        <strong>{activeTask.event_stream_meta.pollIntervalMs || 0}ms</strong>
                        <span>SSE 间隔</span>
                      </div>
                      <div>
                        <strong>{activeTask.event_stream_meta.artifactMode || "detail"}</strong>
                        <span>摘要模式</span>
                      </div>
                    </section>
                    {activeTask.conversation_state.summary && (
                      <section className="agent-diagnostic-state">
                        <strong>确认摘要</strong>
                        <p>{activeTask.conversation_state.summary}</p>
                        {activeTask.conversation_state.globalPreferences.length > 0 && (
                          <div>
                            {activeTask.conversation_state.globalPreferences.map((item) => <em key={item}>{item}</em>)}
                          </div>
                        )}
                      </section>
                    )}
                    <div className="agent-stage-table">
                      {stageMetrics.length === 0 && <div className="agent-empty-row">暂无分步明细</div>}
                      {stageMetrics.map((metric) => (
                        <article key={`${metric.stage}-${metric.agent}-${metric.updatedAt}`} className={metric.errorType ? "is-error" : ""}>
                          <div>
                            <strong>{friendlyProcessLabel(metric.stage)}</strong>
                            <span>{friendlyProcessLabel(metric.agent) || "处理步骤"}</span>
                          </div>
                          <div>
                            <b>{metric.durationMs}ms</b>
                            <span>耗时</span>
                          </div>
                          <div>
                            <b>{metric.modelCalls}</b>
                            <span>生成</span>
                          </div>
                          <div>
                            <b>{metric.cacheHits}/{metric.cacheMisses}</b>
                            <span>{friendlyProcessLabel(metric.cacheNamespace) || "本地复用"}</span>
                          </div>
                          <div>
                            <b>{metric.retryCount}</b>
                            <span>重试</span>
                          </div>
                          <p>{friendlyProcessLabel(metric.errorType || metric.lastMessage)}</p>
                        </article>
                      ))}
                    </div>
                  </div>
                )}

                {resultTab === "logs" && (
                  <div className="agent-terminal">
                    <div className="agent-terminal-filter">
                      {(Object.keys(terminalLabels) as TerminalFilter[]).map((filter) => (
                        <button
                          key={filter}
                          type="button"
                          className={terminalFilter === filter ? "active" : ""}
                          onClick={() => setTerminalFilter(filter)}
                        >
                          {terminalLabels[filter]}
                        </button>
                      ))}
                    </div>
                    <div className="agent-terminal-body">
                      {activeTask.status === "PENDING" && <div className="agent-log-line is-info">任务已入队，正在同步 worker 接手状态。</div>}
                      {filteredLogs.map((log, index) => (
                        <div key={`${log.timestamp}-${index}`} className={`agent-log-line is-${log.type}`}>
                          <time>{formatTime(log.timestamp)}</time>
                          {(log.stage || log.agent || log.durationMs || log.modelId) && (
                            <small className="agent-log-meta">
                              {[log.stage, log.agent, log.modelId, log.durationMs ? `${log.durationMs}ms` : ""].map(friendlyProcessLabel).filter(Boolean).join(" · ")}
                            </small>
                          )}
                          <span>{friendlyProcessLabel(log.message)}</span>
                          {log.detail !== undefined && (
                            <pre>{friendlyLogDetail(log.detail)}</pre>
                          )}
                        </div>
                      ))}
                      {activeTask.status === "RUNNING" && <div className="agent-log-line is-info">正在后台处理。</div>}
                      <div ref={terminalEndRef} />
                    </div>
                  </div>
                )}
              </details>

              </aside>
              </div>
            </>
          ) : (
            <>
              <section className="agent-panel agent-empty-state">
                <span>准备就绪</span>
                <h2>先交给系统读取简历和 JD</h2>
                <p>系统会先基于已有真实经历处理，只有遇到无法确认的关键信息时才停下来询问。</p>
              </section>

              <form className="agent-panel agent-start-panel agent-new-composer" onSubmit={handleStartOptimize}>
                {(uploadMessage || uploadError) && (
                  <div className="agent-composer-notices">
                    {uploadMessage && <div className="agent-note is-success">{uploadMessage}</div>}
                    {uploadError && <div className="agent-note is-danger">{uploadError}</div>}
                  </div>
                )}

                <label className="agent-field agent-jd-field">
                  <span>目标岗位 JD</span>
                  <textarea
                    value={jdText}
                    onChange={(event) => setJdText(event.target.value)}
                    placeholder="粘贴岗位职责、任职要求、技术栈和加分项"
                  />
                </label>

                <div className="agent-composer-toolbar">
                  <label className="agent-upload-chip">
                    <input
                      type="file"
                      accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={(event) => {
                        void handleResumeUpload(event.target.files?.[0] || null);
                        event.currentTarget.value = "";
                      }}
                      disabled={isUploadingResume || isSubmitting}
                    />
                    <span>{isUploadingResume ? "解析中" : "上传简历"}</span>
                  </label>

                  <label className="agent-field compact">
                    <span>简历</span>
                    <select
                      value={selectedResumeId}
                      onChange={(event) => setSelectedResumeId(event.target.value)}
                      disabled={loadingResumes || resumes.length === 0}
                    >
                      {loadingResumes && <option value="">读取中...</option>}
                      {!loadingResumes && resumes.length === 0 && <option value="">暂无简历</option>}
                      {resumes.map((resume) => (
                        <option key={resume.id} value={resume.id}>
                          {resume.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="agent-field compact">
                    <span>模型</span>
                    <select
                      value={selectedConfigId}
                      onChange={(event) => setSelectedConfigId(event.target.value)}
                      disabled={chatConfigs.length === 0}
                    >
                      {chatConfigs.length === 0 && <option value="">暂无可用大语言模型</option>}
                      {chatConfigs.map((config) => (
                        <option key={config.id} value={config.id}>
                          {formatChatConfigLabel(config)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <div className="agent-mode-control">
                    <span>模式</span>
                    <div className="agent-mode-switch" role="group" aria-label="运行模式">
                      <button
                        type="button"
                        className={runMode === "auto" ? "active" : ""}
                        onClick={() => setRunMode("auto")}
                        disabled={isSubmitting || Boolean(activeTaskId)}
                        data-tooltip="优点：最少干预，直接基于已有简历和 JD 生成第一版，适合快速出结果。"
                        title="优点：最少干预，直接基于已有简历和 JD 生成第一版，适合快速出结果。"
                      >
                        自动
                      </button>
                      <button
                        type="button"
                        className={runMode === "copilot" ? "active" : ""}
                        onClick={() => setRunMode("copilot")}
                        disabled={isSubmitting || Boolean(activeTaskId)}
                        data-tooltip="优点：关键事实不确定时会停下来问你，可补充证据、偏好或指令，结果更贴合。"
                        title="优点：关键事实不确定时会停下来问你，可补充证据、偏好或指令，结果更贴合。"
                      >
                        对话
                      </button>
                    </div>
                  </div>

                  <div className="agent-mode-control">
                    <span>执行</span>
                    <div className="agent-mode-switch" role="group" aria-label="执行路径">
                      <button
                        type="button"
                        className={executionMode === "pipeline" ? "active" : ""}
                        onClick={() => setExecutionMode("pipeline")}
                        disabled={isSubmitting || Boolean(activeTaskId)}
                        data-tooltip="优点：固定流程更稳定，总耗时更可控，适合一键生成投递版本。"
                        title="优点：固定流程更稳定，总耗时更可控，适合一键生成投递版本。"
                      >
                        流水线
                      </button>
                      <button
                        type="button"
                        className={executionMode === "agentic" ? "active" : ""}
                        onClick={() => setExecutionMode("agentic")}
                        disabled={isSubmitting || Boolean(activeTaskId)}
                        data-tooltip="优点：像 Codex 一样现场读文件、调用工具、失败自修正，可以看见改简历过程。"
                        title="优点：像 Codex 一样现场读文件、调用工具、失败自修正，可以看见改简历过程。"
                      >
                        Agentic
                      </button>
                    </div>
                  </div>

                  <div className="agent-mode-control is-wide">
                    <span>工具调用</span>
                    <div className="agent-mode-switch" role="group" aria-label="工具调用方式">
                      <button
                        type="button"
                        className={toolCallingMode === "json_action" ? "active" : ""}
                        onClick={() => setToolCallingMode("json_action")}
                        disabled={isSubmitting || Boolean(activeTaskId) || executionMode !== "agentic"}
                        data-tooltip="优点：兼容性最好，适合大多数 OpenAI 兼容模型；仅 Agentic 模式生效。"
                        title="优点：兼容性最好，适合大多数 OpenAI 兼容模型；仅 Agentic 模式生效。"
                      >
                        JSON
                      </button>
                      <button
                        type="button"
                        className={toolCallingMode === "native_responses" ? "active" : ""}
                        onClick={() => setToolCallingMode("native_responses")}
                        disabled={isSubmitting || Boolean(activeTaskId) || executionMode !== "agentic"}
                        data-tooltip="优点：模型原生工具调用更结构化，provider 支持时解析更稳；仅 Agentic 模式生效。"
                        title="优点：模型原生工具调用更结构化，provider 支持时解析更稳；仅 Agentic 模式生效。"
                      >
                        原生
                      </button>
                    </div>
                  </div>

                  <button className="agent-primary-button" type="submit" disabled={isSubmitting || isUploadingResume || Boolean(activeTaskId) || !selectedConfigId}>
                    {isSubmitting ? "创建中..." : activeTaskId ? "正在处理" : "开始"}
                  </button>
                </div>

                <small className="agent-field-help">
                  {selectedChatConfig
                    ? `将使用 ${selectedChatConfig.provider} / ${selectedChatConfig.modelId}`
                    : "请先在设置中配置并启用大语言模型。"}
                  {` 执行：${executionModeLabels[executionMode]} / ${toolCallingModeLabels[executionMode === "agentic" ? toolCallingMode : "auto"]}`}
                  {selectedResume ? ` 当前简历：${selectedResume.name} · ${formatFileSize(selectedResume.size || 0)}` : ""}
                </small>
              </form>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
