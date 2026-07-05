import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, MouseEvent } from "react";
import { ResumeDiffView } from "../components/resume/ResumeDiffView";
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

interface ModelConfig {
  id: string;
  provider: string;
  modelId: string;
  name?: string;
  display_name?: string;
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
  retryCount?: number;
  errorType?: string;
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
  savedModelCalls: number;
  items: CacheStatsItem[];
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

interface AgentTask {
  task_id: string;
  trace_id?: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "WAITING_FOR_HUMAN";
  resume_id: string;
  original_resume_name: string;
  jd_text: string;
  logs: AgentLog[];
  optimized_resume_md: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  modification_diff_md: string;
  has_docx: boolean;
  modification_log: ModificationItem[];
  pending_question?: string;
  human_answer?: string;
  execution_plan?: string;
  conversation_turns: AgentTurn[];
  conversation_state: AgentConversationState;
  cache_stats: CacheStats;
  stage_metrics: AgentStageMetric[];
}

type AgentMode = "auto" | "dialog";
type AnswerType = "evidence" | "preference" | "clarification" | "instruction" | "question";
type EvidenceScope = "current_step" | "resume" | "jd" | "global";
type ResultTab = "resume" | "diff" | "insights" | "diagnostics" | "logs";
type TerminalFilter = "all" | "thought" | "tool";
type CopyTarget = "resume" | "action-pack" | "text";

const terminalLabels: Record<TerminalFilter, string> = {
  all: "全部",
  thought: "说明",
  tool: "操作",
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

const modeTitle: Record<AgentMode, string> = {
  auto: "快速生成",
  dialog: "边确认边改",
};

const evidenceScopeLabels: Record<EvidenceScope, string> = {
  current_step: "当前段落",
  resume: "整份简历",
  jd: "目标岗位",
  global: "长期偏好",
};

function friendlyProcessLabel(value?: string | number | null): string {
  if (value === undefined || value === null) return "";
  return String(value)
    .replace(/防幻觉/g, "事实核对")
    .replace(/段落改写/g, "段落调整")
    .replace(/JD 解码/g, "岗位要求读取")
    .replace(/执行计划/g, "处理计划")
    .replace(/Agent/gi, "工作台")
    .replace(/AI/g, "")
    .replace(/大模型/g, "生成服务")
    .replace(/模型调用/g, "生成次数")
    .replace(/模型/g, "生成配置")
    .replace(/缓存/g, "复用")
    .replace(/stage/gi, "步骤")
    .trim();
}

function friendlyLogDetail(detail: unknown): string {
  const text = typeof detail === "string" ? detail : JSON.stringify(detail, null, 2);
  return friendlyProcessLabel(text);
}

function parseApiError(response: Response, fallback: string): Promise<string> {
  return response.json()
    .then((body: { detail?: string }) => body.detail || fallback)
    .catch(() => fallback);
}

function parseLogs(raw: unknown): AgentLog[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as AgentLog[];
  if (typeof raw !== "string") return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function emptyCacheStats(): CacheStats {
  return {
    hits: 0,
    misses: 0,
    savedModelCalls: 0,
    items: [],
  };
}

function toNumber(value: unknown): number {
  const next = Number(value);
  return Number.isFinite(next) ? next : 0;
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
    savedModelCalls: toNumber(raw.savedModelCalls),
    items,
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
    error_message: task.errorMessage || "",
    created_at: task.createdAt,
    updated_at: task.updatedAt,
    modification_diff_md: task.modificationDiffMd || "",
    has_docx: Boolean(task.hasDocx),
    modification_log: Array.isArray(task.modificationLog) ? task.modificationLog : [],
    pending_question: task.pendingQuestion || "",
    human_answer: task.humanAnswer || "",
    execution_plan: task.executionPlan || "",
    conversation_turns: parseConversationTurns(task.conversationTurns),
    conversation_state: parseConversationState(task.conversationState),
    cache_stats: parseCacheStats(task.cacheStats),
    stage_metrics: parseStageMetrics(task.stageMetrics),
  };
}

function mapTaskFromDetail(data: any): AgentTask {
  return mapTaskFromApi(data);
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

export function AgentResumePage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [chatConfigs, setChatConfigs] = useState<ModelConfig[]>([]);
  const [tasks, setTasks] = useState<AgentTask[]>([]);

  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [jdText, setJdText] = useState("");
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [mode, setMode] = useState<AgentMode>("auto");

  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeTask, setActiveTask] = useState<AgentTask | null>(null);
  const [pollingTrigger, setPollingTrigger] = useState(0);

  const [isUploadingResume, setIsUploadingResume] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmittingAnswer, setIsSubmittingAnswer] = useState(false);
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
  const [terminalFilter, setTerminalFilter] = useState<TerminalFilter>("all");
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
  const copyResetRef = useRef<number | null>(null);

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
      const [resumeResponse, configResponse] = await Promise.all([
        fetch("/api/resumes"),
        fetch("/api/models/configs"),
      ]);

      if (resumeResponse.ok) {
        const data = await resumeResponse.json();
        const nextResumes = data.resumes || [];
        setResumes(nextResumes);
        if (!selectedResumeId && nextResumes.length > 0) {
          setSelectedResumeId(nextResumes[0].id);
        }
      }

      if (configResponse.ok) {
        const data = await configResponse.json();
        setChatConfigs(data.chatConfigs || []);
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
    if (!activeTaskId) return;

    let cancelled = false;
    let timerId: number | undefined;

    const tick = async () => {
      const task = await fetchTaskDetail(activeTaskId);
      if (cancelled || !task) return;
      setActiveTask(task);
      if (task.status === "COMPLETED" || task.status === "FAILED" || task.status === "WAITING_FOR_HUMAN") {
        if (task.status !== "WAITING_FOR_HUMAN") {
          setActiveTaskId(null);
        }
        void loadTasks();
        return;
      }
      timerId = window.setTimeout(tick, 1500);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timerId) window.clearTimeout(timerId);
    };
  }, [activeTaskId, fetchTaskDetail, loadTasks, pollingTrigger]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
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

    setIsSubmitting(true);
    setUploadError("");
    try {
      const response = await fetch("/api/agent/resume/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: selectedResumeId,
          jd_text: jdText.trim(),
          config_id: selectedConfigId || null,
          is_co_pilot: mode === "dialog",
        }),
      });

      if (!response.ok) {
        throw new Error(await parseApiError(response, "启动简历优化失败"));
      }

      const data = await response.json();
      if (data.cacheHit) {
        setUploadMessage(data.message || "已复用相同输入的历史任务");
        const cachedTask = await fetchTaskDetail(data.taskId);
        if (cachedTask) {
          setActiveTask(cachedTask);
          setResultTab(cachedTask.status === "COMPLETED" ? "resume" : "logs");
          if (cachedTask.status === "PENDING" || cachedTask.status === "RUNNING" || cachedTask.status === "WAITING_FOR_HUMAN") {
            setActiveTaskId(cachedTask.task_id);
          }
        }
        void loadTasks();
        return;
      }

      const newTask: AgentTask = {
        task_id: data.taskId,
        status: "PENDING",
        resume_id: selectedResumeId,
        original_resume_name: selectedResume?.name || "resume.pdf",
        jd_text: jdText.trim(),
        logs: [],
        optimized_resume_md: "",
        error_message: "",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        modification_diff_md: "",
        has_docx: false,
        modification_log: [],
        conversation_turns: [],
        conversation_state: { summary: "", globalPreferences: [], factLedger: [], updatedAt: "" },
        cache_stats: emptyCacheStats(),
        stage_metrics: [],
      };
      setActiveTask(newTask);
      setActiveTaskId(data.taskId);
      setResultTab("logs");
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
    setResultTab(task.status === "COMPLETED" ? "resume" : "logs");
    const detail = await fetchTaskDetail(task.task_id);
    if (detail) setActiveTask(detail);
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
      setHumanAnswerText("");
      setAnswerType("evidence");
      setEvidenceScope("current_step");
      setRememberAnswer(true);
      setPollingTrigger((value) => value + 1);
      setActiveTaskId(activeTask.task_id);
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
  const activeCacheStats = activeTask?.cache_stats || emptyCacheStats();
  const cacheTotal = activeCacheStats.hits + activeCacheStats.misses;
  const cacheHitRate = cacheTotal > 0 ? Math.round((activeCacheStats.hits / cacheTotal) * 100) : 0;
  const recentCacheItems = activeCacheStats.items.slice(-6).reverse();
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
        hitRate: cacheHitRate,
        hits: activeCacheStats.hits,
        misses: activeCacheStats.misses,
        savedModelCalls: activeCacheStats.savedModelCalls,
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
    cacheHitRate,
    activeCacheStats.hits,
    activeCacheStats.misses,
    activeCacheStats.savedModelCalls,
  ]);

  return (
    <div className="page-stack agent-page">
      <header className="analysis-hero agent-header">
        <div>
          <span className="section-kicker">简历定向优化</span>
          <h2>把简历改到这次岗位上</h2>
          <p>选择一份简历，粘贴岗位 JD，生成可下载的投递版本和修改对照。</p>
        </div>
        <div className="analysis-hero-meta agent-header-metrics" aria-label="简历优化保障">
          <span>复用历史结果</span>
          <span>基于真实经历</span>
          <span>保留原简历版式</span>
          <span>需要时再确认</span>
        </div>
      </header>

      <div className="agent-workbench">
        <aside className="agent-side">
          <form className="agent-panel agent-start-panel" onSubmit={handleStartOptimize}>
            <div className="agent-panel-title">
              <span>新任务</span>
              <strong>{modeTitle[mode]}</strong>
            </div>

            <label className="agent-upload-zone">
              <input
                type="file"
                accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(event) => {
                  void handleResumeUpload(event.target.files?.[0] || null);
                  event.currentTarget.value = "";
                }}
                disabled={isUploadingResume || isSubmitting}
              />
              <span>{isUploadingResume ? "解析中" : "上传 PDF / DOCX"}</span>
              <small>{selectedResume ? `${selectedResume.name} · ${formatFileSize(selectedResume.size || 0)}` : "未选择简历"}</small>
            </label>

            {uploadMessage && <div className="agent-note is-success">{uploadMessage}</div>}
            {uploadError && <div className="agent-note is-danger">{uploadError}</div>}

            <label className="agent-field">
              <span>历史简历</span>
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

            <div className="agent-mode-switch" role="group" aria-label="生成方式">
              <button
                type="button"
                className={mode === "auto" ? "active" : ""}
                onClick={() => setMode("auto")}
              >
                快速
              </button>
              <button
                type="button"
                className={mode === "dialog" ? "active" : ""}
                onClick={() => setMode("dialog")}
              >
                确认
              </button>
            </div>

            <label className="agent-field">
              <span>目标岗位 JD</span>
              <textarea
                value={jdText}
                onChange={(event) => setJdText(event.target.value)}
                placeholder="粘贴岗位职责、任职要求、技术栈和加分项"
              />
            </label>

            <label className="agent-field">
              <span>生成配置</span>
              <select value={selectedConfigId} onChange={(event) => setSelectedConfigId(event.target.value)}>
                <option value="">系统默认</option>
                {chatConfigs.map((config) => (
                  <option key={config.id} value={config.id}>
                    {config.display_name || config.name || `${config.provider} · ${config.modelId}`}
                  </option>
                ))}
              </select>
            </label>

            <button className="agent-primary-button" type="submit" disabled={isSubmitting || isUploadingResume || Boolean(activeTaskId)}>
              {isSubmitting ? "创建中..." : activeTaskId ? "正在处理" : "开始生成"}
            </button>
          </form>

          <section className="agent-panel agent-history-panel">
            <div className="agent-panel-title">
              <span>优化记录</span>
              <strong>{loadingTasks ? "读取中" : `${tasks.length} 条`}</strong>
            </div>
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
          {activeTask ? (
            <>
              <section className="agent-panel agent-status-panel">
                <div>
                  <span className={`agent-status is-${activeTask.status.toLowerCase()}`}>{statusLabels[activeTask.status]}</span>
                  <h2>{activeTask.original_resume_name}</h2>
                  <p>{activeTask.status === "COMPLETED" ? "投递版本已生成" : "正在按真实经历处理简历"}</p>
                </div>
                <div className="agent-cache-strip" aria-label="复用情况">
                  <div>
                    <strong>{cacheHitRate}%</strong>
                    <span>结果复用率</span>
                  </div>
                  <div>
                    <strong>{activeCacheStats.hits}/{cacheTotal}</strong>
                    <span>复用/检查</span>
                  </div>
                  <div>
                    <strong>{activeCacheStats.savedModelCalls}</strong>
                    <span>节省生成次数</span>
                  </div>
                  {recentCacheItems.length > 0 && (
                    <div className="agent-cache-events">
                      {recentCacheItems.map((item, index) => (
                        <em key={`${item.namespace}-${item.label}-${index}`} className={item.hit ? "hit" : "miss"}>
                          {item.hit ? "已复用" : "新生成"} {friendlyProcessLabel(item.label)}
                        </em>
                      ))}
                    </div>
                  )}
                </div>
                <div className="agent-progress">
                  <strong>{completedSteps}/4</strong>
                  <span>读取 · 核对 · 排版 · 完成</span>
                </div>
              </section>

              {activeTask.status === "WAITING_FOR_HUMAN" && (
                <section className="agent-panel agent-human-panel">
                  <strong>需要确认</strong>
                  <p>{activeTask.pending_question || "请补充可确认的项目细节，或选择无补充继续。"}</p>
                  <div className="agent-answer-controls">
                    <div className="agent-answer-type" role="group" aria-label="answer type">
                      {(Object.keys(answerTypeLabels) as AnswerType[]).map((type) => (
                        <button
                          key={type}
                          type="button"
                          className={answerType === type ? "active" : ""}
                          onClick={() => setAnswerType(type)}
                          disabled={isSubmittingAnswer}
                        >
                          {answerTypeLabels[type]}
                        </button>
                      ))}
                    </div>
                    <select
                      value={evidenceScope}
                      onChange={(event) => setEvidenceScope(event.target.value as EvidenceScope)}
                      disabled={isSubmittingAnswer}
                    >
                      {(Object.keys(evidenceScopeLabels) as EvidenceScope[]).map((scope) => (
                        <option key={scope} value={scope}>{evidenceScopeLabels[scope]}</option>
                      ))}
                    </select>
                  </div>
                  <textarea
                    value={humanAnswerText}
                    onChange={(event) => setHumanAnswerText(event.target.value)}
                    placeholder={answerTypePlaceholders[answerType]}
                    disabled={isSubmittingAnswer}
                  />
                  <label className="agent-memory-toggle">
                    <input
                      type="checkbox"
                      checked={rememberAnswer}
                      onChange={(event) => setRememberAnswer(event.target.checked)}
                      disabled={isSubmittingAnswer}
                    />
                    <span>保存为本次任务的后续规则</span>
                  </label>
                  <div className="agent-human-actions">
                    <button type="button" onClick={() => void handleSubmitAnswer("无补充，请保持原始事实继续。", false, "skip")} disabled={isSubmittingAnswer}>
                      无补充
                    </button>
                    <button
                      type="button"
                      className="agent-primary-button compact"
                      onClick={() => {
                        if (!humanAnswerText.trim()) {
                          setUploadError("请填写补充内容，或选择无补充");
                          return;
                        }
                        void handleSubmitAnswer(humanAnswerText.trim(), rememberAnswer, answerType);
                      }}
                      disabled={isSubmittingAnswer}
                    >
                      提交
                    </button>
                  </div>
                </section>
              )}

              {conversationTurns.length > 0 && (
                <details className="agent-panel agent-conversation" open={activeTask.status === "WAITING_FOR_HUMAN"}>
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

              <section className="agent-panel agent-result-panel">
                <div className="agent-result-toolbar">
                  <div className="agent-tabs" role="tablist">
                    <button type="button" className={resultTab === "resume" ? "active" : ""} onClick={() => setResultTab("resume")}>简历</button>
                    <button type="button" className={resultTab === "diff" ? "active" : ""} onClick={() => setResultTab("diff")}>对照</button>
                    <button type="button" className={resultTab === "insights" ? "active" : ""} onClick={() => setResultTab("insights")}>行动台</button>
                    <button type="button" className={resultTab === "diagnostics" ? "active" : ""} onClick={() => setResultTab("diagnostics")}>运行明细</button>
                    <button type="button" className={resultTab === "logs" ? "active" : ""} onClick={() => setResultTab("logs")}>过程记录</button>
                  </div>

                  {activeTask.status === "COMPLETED" && (
                    <div className="agent-actions">
                      <button type="button" onClick={() => void handleCopyMarkdown()}>{copiedTarget === "resume" ? "已复制" : "复制 MD"}</button>
                      <button type="button" onClick={() => void handleCopyActionPack()}>{copiedTarget === "action-pack" ? "已复制" : "复制行动包"}</button>
                      <button type="button" onClick={handleDownloadActionPack}>下载行动包</button>
                      <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download`}>MD</a>
                      <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download?format=docx`}>DOCX</a>
                      <a href={`/api/agent/resume/tasks/${activeTask.task_id}/download?format=pdf`}>PDF</a>
                    </div>
                  )}
                </div>

                {resultTab === "resume" && (
                  <pre className="agent-resume-preview">
                    {activeTask.optimized_resume_md || (activeTask.status === "FAILED" ? activeTask.error_message : "等待生成结果...")}
                  </pre>
                )}

                {resultTab === "diff" && (
                  activeTask.modification_log.length > 0
                    ? <ResumeDiffView modificationLog={activeTask.modification_log} />
                    : <div className="agent-empty-row">暂无修改对照</div>
                )}

                {resultTab === "insights" && (
                  <div className="agent-insights">
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
                        <strong>{totalSavedModelCalls || activeCacheStats.savedModelCalls}</strong>
                        <span>复用节省</span>
                      </div>
                      <div>
                        <strong>{activeCacheStats.hits}/{activeCacheStats.misses}</strong>
                        <span>复用/新算</span>
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
                            <span>{friendlyProcessLabel(metric.cacheNamespace) || "复用"}</span>
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
                      {activeTask.status === "PENDING" && <div className="agent-log-line is-info">任务已创建，等待后台启动。</div>}
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
              </section>
            </>
          ) : (
            <section className="agent-panel agent-empty-state">
              <span>准备就绪</span>
              <h2>选择简历和 JD 后开始</h2>
              <p>快速生成会直接产出投递版本；确认模式会在需要补充真实细节时停下来。</p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
