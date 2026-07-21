import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgentActivityBar } from "../features/resumeAdvisor/AgentActivityBar";
import { AgentTimeline } from "../features/resumeAdvisor/AgentTimeline";
import { AdvisorSloPanel } from "../features/resumeAdvisor/AdvisorSloPanel";
import { ConversationThread } from "../features/resumeAdvisor/ConversationThread";
import { MessageComposer } from "../features/resumeAdvisor/MessageComposer";
import { OriginalResumeViewer } from "../features/resumeAdvisor/OriginalResumeViewer";
import { SessionSidebar } from "../features/resumeAdvisor/SessionSidebar";
import { SuggestionWorkspace } from "../features/resumeAdvisor/SuggestionWorkspace";
import { resumeAdvisorApi } from "../features/resumeAdvisor/api";
import { ProjectKnowledgePanel } from "../features/projectKnowledge/ProjectKnowledgeSelector";
import {
  deleteProjectKnowledgeDocument,
  fetchProjectKnowledgeDocuments,
  uploadProjectKnowledgeDocument,
} from "../services/projectKnowledgeService";
import type { ProjectKnowledgeDocument, ProjectKnowledgeScope } from "../types/projectKnowledge";
import type { AdvisorEvent, AdvisorSession, AdvisorSloDashboard, AdvisorSnapshot, ResumeBlock, ResumePreview, ResumeSuggestion, ResumeSummary } from "../features/resumeAdvisor/types";

function newClientMessageId(): string {
  return typeof crypto?.randomUUID === "function" ? crypto.randomUUID() : `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface AdvisorLiveState {
  runId: string;
  active: boolean;
  title: string;
  detail: string;
  liveText: string;
  cacheLabel: string;
  providerCacheLabel: string;
  firstTokenMs: number | null;
}

function eventText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function eventNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = Number(payload[key]);
  return Number.isFinite(value) ? value : null;
}

function normalizedProjectFileName(fileName: string): string {
  return fileName.trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

export function ResumeAdvisorPage() {
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [sessions, setSessions] = useState<AdvisorSession[]>([]);
  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [jdText, setJdText] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<AdvisorSnapshot | null>(null);
  const [blocks, setBlocks] = useState<ResumeBlock[]>([]);
  const [preview, setPreview] = useState<ResumePreview | null>(null);
  const [sloDashboard, setSloDashboard] = useState<AdvisorSloDashboard | null>(null);
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingResumeId, setDeletingResumeId] = useState<string | null>(null);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [projectKnowledgeDocuments, setProjectKnowledgeDocuments] = useState<ProjectKnowledgeDocument[]>([]);
  const [selectedProjectKnowledgeIds, setSelectedProjectKnowledgeIds] = useState<number[]>([]);
  const [projectKnowledgeLoading, setProjectKnowledgeLoading] = useState(false);
  const [projectKnowledgeError, setProjectKnowledgeError] = useState<string | null>(null);
  const [projectKnowledgeUploadProgress, setProjectKnowledgeUploadProgress] = useState<{ completed: number; total: number } | null>(null);
  const [failedProjectKnowledgeUploads, setFailedProjectKnowledgeUploads] = useState<Array<{ file: File; message: string }>>([]);
  const [liveState, setLiveState] = useState<AdvisorLiveState | null>(null);
  const latestEventSequenceRef = useRef(0);
  const projectKnowledgeInitializedRef = useRef(false);

  const refreshLists = useCallback(async () => {
    const [nextResumes, nextSessions] = await Promise.all([resumeAdvisorApi.listResumes(), resumeAdvisorApi.listSessions()]);
    setResumes(nextResumes);
    setSessions(nextSessions);
    setSelectedResumeId((current) => current || nextResumes.find((resume) => resume.isCurrent)?.id || nextResumes[0]?.id || "");
  }, []);

  const refreshSnapshot = useCallback(async (sessionId: string) => {
    const nextSnapshot = await resumeAdvisorApi.getSnapshot(sessionId);
    setSnapshot(nextSnapshot);
    return nextSnapshot;
  }, []);

  const refreshSession = useCallback(async (sessionId: string) => {
    const [nextSnapshot, resumeView] = await Promise.all([resumeAdvisorApi.getSnapshot(sessionId), resumeAdvisorApi.getResumeView(sessionId)]);
    setSnapshot(nextSnapshot);
    setBlocks(resumeView.blocks || []);
    setPreview(resumeView.preview || null);
  }, []);

  const refreshSloDashboard = useCallback(async () => {
    setSloDashboard(await resumeAdvisorApi.getSloDashboard());
  }, []);

  const refreshProjectKnowledge = useCallback(async () => {
    setProjectKnowledgeLoading(true);
    setProjectKnowledgeError(null);
    try {
      const documents = await fetchProjectKnowledgeDocuments();
      setProjectKnowledgeDocuments(documents);
      setSelectedProjectKnowledgeIds((current) => {
        const ids = documents.map((document) => document.id);
        if (!projectKnowledgeInitializedRef.current) {
          projectKnowledgeInitializedRef.current = true;
          return ids;
        }
        return current.filter((id) => ids.includes(id));
      });
    } catch (reason) {
      setProjectKnowledgeError(reason instanceof Error ? reason.message : "无法加载项目知识库。");
    } finally {
      setProjectKnowledgeLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshLists().catch((reason) => setError(reason instanceof Error ? reason.message : "无法加载简历会话。"));
  }, [refreshLists]);

  useEffect(() => {
    void refreshSloDashboard().catch(() => undefined);
  }, [refreshSloDashboard]);

  useEffect(() => {
    void refreshProjectKnowledge();
  }, [refreshProjectKnowledge]);

  useEffect(() => {
    const rawContext = sessionStorage.getItem("internpath:resume-advisor-launch");
    if (!rawContext) return;
    sessionStorage.removeItem("internpath:resume-advisor-launch");
    try {
      const context = JSON.parse(rawContext) as { resumeId?: string; jdText?: string };
      if (context.resumeId) setSelectedResumeId(context.resumeId);
      if (context.jdText) setJdText(context.jdText);
    } catch {
      // Stale navigation context is non-authoritative and can be ignored.
    }
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      setSnapshot(null);
      setBlocks([]);
      setPreview(null);
      setLiveState(null);
      return;
    }
    latestEventSequenceRef.current = 0;
    void refreshSession(selectedSessionId).catch((reason) => setError(reason instanceof Error ? reason.message : "无法读取会话。"));
  }, [refreshSession, selectedSessionId]);

  const activeRunId = snapshot?.run?.id || "";
  const activeRunStatus = snapshot?.run?.status || "";

  useEffect(() => {
    if (!selectedSessionId || !activeRunId || !["QUEUED", "RUNNING"].includes(activeRunStatus)) return;
    let stopped = false;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;
    const reconcile = (title: string) => {
      void refreshSnapshot(selectedSessionId).then(() => {
        setLiveState((current) => current?.runId === activeRunId ? { ...current, active: false, title, liveText: "" } : current);
        void refreshSloDashboard().catch(() => undefined);
      }).catch(() => undefined);
    };
    const handleEvent = (eventName: string, event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      let data: AdvisorEvent;
      try {
        data = JSON.parse(messageEvent.data) as AdvisorEvent;
      } catch {
        return;
      }
      if (typeof data.sequence === "number") {
        if (data.sequence <= latestEventSequenceRef.current) return;
        latestEventSequenceRef.current = data.sequence;
      }
      if (data.runId && data.runId !== activeRunId) return;
      const payload = data.payload && typeof data.payload === "object" ? data.payload : {};
      setSnapshot((current) => {
        if (!current || current.session.id !== selectedSessionId) return current;
        if (current.events.some((entry) => entry.id === data.id)) return current;
        return { ...current, events: [...current.events, data].slice(-160) };
      });

      if (eventName === "model_delta") {
        const delta = eventText(payload, "delta");
        if (!delta) return;
        setLiveState((current) => ({
          runId: activeRunId,
          active: true,
          title: "GPT 正在流式生成回复",
          detail: eventText(payload, "agent") || "resume_copywriter",
          liveText: `${current?.runId === activeRunId ? current.liveText : ""}${delta}`,
          cacheLabel: current?.runId === activeRunId ? current.cacheLabel : "",
          providerCacheLabel: current?.runId === activeRunId ? current.providerCacheLabel : "",
          firstTokenMs: current?.runId === activeRunId && current.firstTokenMs !== null
            ? current.firstTokenMs
            : eventNumber(payload, "endToEndFirstTokenMs") ?? eventNumber(payload, "firstTokenMs"),
        }));
        return;
      }

      if (eventName === "cache") {
        const namespace = eventText(payload, "namespace") || "Advisor 缓存";
        const hit = payload.hit === true;
        setLiveState((current) => ({
          runId: activeRunId, active: true,
          title: current?.title || "正在准备模型上下文",
          detail: current?.detail || namespace,
          liveText: current?.liveText || "",
          cacheLabel: `${namespace} ${hit ? "命中" : "未命中"}`,
          providerCacheLabel: current?.providerCacheLabel || "",
          firstTokenMs: current?.firstTokenMs ?? null,
        }));
        return;
      }

      if (eventName === "provider_usage") {
        const available = payload.providerCacheAvailable === true;
        const hit = payload.providerCacheHit === true;
        const cachedTokens = eventNumber(payload, "providerCachedTokens") || 0;
        setLiveState((current) => ({
          runId: activeRunId, active: true,
          title: current?.title || "模型调用已返回",
          detail: current?.detail || eventText(payload, "agent"),
          liveText: current?.liveText || "",
          cacheLabel: current?.cacheLabel || "",
          providerCacheLabel: available ? `Provider 缓存${hit ? `命中 ${cachedTokens} tokens` : "未命中"}` : "Provider 未上报缓存",
          firstTokenMs: current?.firstTokenMs ?? null,
        }));
        return;
      }

      if (eventName === "progress" || eventName === "tool_call" || eventName === "tool_result") {
        const title = eventName === "tool_call"
          ? `正在调用 ${eventText(payload, "toolName") || "工具"}`
          : eventName === "tool_result"
            ? `${eventText(payload, "toolName") || "工具"} 已完成`
            : eventText(payload, "summary") || "正在分析简历";
        setLiveState((current) => ({
          runId: activeRunId, active: true, title,
          detail: eventText(payload, "agent") || eventText(payload, "stage"),
          liveText: current?.liveText || "",
          cacheLabel: current?.cacheLabel || "",
          providerCacheLabel: current?.providerCacheLabel || "",
          firstTokenMs: current?.firstTokenMs ?? null,
        }));
        return;
      }

      if (["message", "suggestion", "suggestion_action", "suggestion_restored", "question", "session_finished", "run_cancelled", "error"].includes(eventName)) {
        if (eventName === "error") setError(eventText(payload, "error") || "本轮分析失败，请重试。");
        reconcile(eventName === "error" ? "本轮运行失败" : "本轮回复已完成");
      }
    };
    const connect = () => {
      if (stopped) return;
      setLiveState((current) => ({
        runId: activeRunId, active: true,
        title: current?.runId === activeRunId ? current.title : "正在连接实时模型流",
        detail: current?.runId === activeRunId ? current.detail : "等待专用 Advisor worker 输出真实 token",
        liveText: current?.runId === activeRunId ? current.liveText : "",
        cacheLabel: current?.runId === activeRunId ? current.cacheLabel : "",
        providerCacheLabel: current?.runId === activeRunId ? current.providerCacheLabel : "",
        firstTokenMs: current?.runId === activeRunId ? current.firstTokenMs : null,
      }));
      source = new EventSource(`/api/agent/resume/sessions/${encodeURIComponent(selectedSessionId)}/events?afterSequence=${latestEventSequenceRef.current}`);
      source.onopen = () => setLiveState((current) => current?.runId === activeRunId ? { ...current, active: true, detail: current.detail || "实时连接已建立" } : current);
      ["message", "suggestion", "suggestion_action", "suggestion_restored", "session_finished", "run_cancelled", "error", "progress", "question", "model_delta", "cache", "provider_usage", "tool_call", "tool_result"].forEach((name) => {
        source?.addEventListener(name, (event) => handleEvent(name, event));
      });
      source.addEventListener("done", () => {
        source?.close();
        if (!stopped) reconcile("本轮回复已完成");
      });
      source.onerror = () => {
        source?.close();
        if (!stopped) {
          setLiveState((current) => current?.runId === activeRunId ? { ...current, active: true, title: "实时连接中断，正在重连" } : current);
          retryTimer = window.setTimeout(connect, 800);
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      source?.close();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [activeRunId, activeRunStatus, refreshSloDashboard, refreshSnapshot, selectedSessionId]);

  const selectedSession = snapshot?.session ?? sessions.find((session) => session.id === selectedSessionId) ?? null;
  const isClosed = selectedSession?.sessionStatus === "SATISFIED" || selectedSession?.sessionStatus === "ARCHIVED";
  const readyToFinish = selectedSession?.sessionStatus === "READY_FOR_CONFIRMATION";
  const isWaitingForAgent = Boolean(selectedSessionId && snapshot?.run && ["QUEUED", "RUNNING"].includes(snapshot.run.status));

  async function startSession() {
    setStarting(true);
    setError("");
    setLiveState({ runId: "pending", active: true, title: "正在提交分析任务", detail: "准备进入专用 Advisor 队列", liveText: "", cacheLabel: "", providerCacheLabel: "", firstTokenMs: null });
    try {
      const availableProjectIds = projectKnowledgeDocuments.map((document) => document.id);
      const projectIds = selectedProjectKnowledgeIds.filter((id) => availableProjectIds.includes(id));
      const projectKnowledgeScope: ProjectKnowledgeScope = projectIds.length === 0
        ? "none"
        : projectIds.length === availableProjectIds.length
          ? "all"
          : "selected";
      const result = await resumeAdvisorApi.startSession({
        resumeId: selectedResumeId,
        jdText,
        projectKnowledgeScope,
        projectKnowledgeDocumentIds: projectIds,
      });
      setSnapshot({ session: result.session, run: result.run, messages: [], suggestions: [], facts: [], events: [] });
      setLiveState({ runId: result.run.id, active: true, title: "任务已进入专用 Advisor 队列", detail: "正在等待模型流连接", liveText: "", cacheLabel: "", providerCacheLabel: "", firstTokenMs: null });
      setSelectedSessionId(result.session.id);
      setJdText("");
      await refreshLists();
    } catch (reason) {
      setLiveState(null);
      setError(reason instanceof Error ? reason.message : "创建会话失败。");
    } finally {
      setStarting(false);
    }
  }

  async function uploadResume(file: File) {
    setUploading(true);
    setError("");
    try {
      const result = await resumeAdvisorApi.uploadResume(file);
      await refreshLists();
      setSelectedResumeId(result.resumeFile.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历上传失败。");
    } finally {
      setUploading(false);
    }
  }

  async function deleteResume(resumeId: string) {
    const resume = resumes.find((item) => item.id === resumeId);
    if (!window.confirm(`删除简历“${resume?.name || "该简历"}”？该操作不会删除已有会话的不可变快照。`)) return;
    setDeletingResumeId(resumeId);
    setError("");
    try {
      await resumeAdvisorApi.deleteResume(resumeId);
      setSelectedResumeId((current) => current === resumeId ? "" : current);
      await refreshLists();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除简历失败。");
    } finally {
      setDeletingResumeId(null);
    }
  }

  async function uploadProjectKnowledge(files: File[]) {
    if (!files.length) return;
    const existingNames = new Set(
      projectKnowledgeDocuments.map((document) => normalizedProjectFileName(document.file_name || document.title)),
    );
    const queuedNames = new Set<string>();
    const skippedFiles: File[] = [];
    const filesToUpload = files.filter((file) => {
      const normalizedName = normalizedProjectFileName(file.name);
      if (existingNames.has(normalizedName) || queuedNames.has(normalizedName)) {
        skippedFiles.push(file);
        return false;
      }
      queuedNames.add(normalizedName);
      return true;
    });
    if (!filesToUpload.length) {
      setProjectKnowledgeError(`已跳过 ${skippedFiles.length} 份同名项目资料。`);
      return;
    }
    setProjectKnowledgeLoading(true);
    setProjectKnowledgeError(null);
    setFailedProjectKnowledgeUploads([]);
    setProjectKnowledgeUploadProgress({ completed: 0, total: filesToUpload.length });
    try {
      const uploaded: ProjectKnowledgeDocument[] = [];
      const failures: Array<{ file: File; message: string }> = [];
      for (const [index, file] of filesToUpload.entries()) {
        try {
          uploaded.push(await uploadProjectKnowledgeDocument(file));
        } catch (reason) {
          failures.push({
            file,
            message: reason instanceof Error ? reason.message : "上传失败",
          });
        } finally {
          setProjectKnowledgeUploadProgress({ completed: index + 1, total: filesToUpload.length });
        }
      }

      if (uploaded.length) {
        setProjectKnowledgeDocuments((current) => {
          const byId = new Map(current.map((document) => [document.id, document]));
          uploaded.forEach((document) => byId.set(document.id, document));
          return [...byId.values()];
        });
        setSelectedProjectKnowledgeIds((current) => [...new Set([...current, ...uploaded.map((document) => document.id)])]);
        projectKnowledgeInitializedRef.current = true;
      }
      if (failures.length) {
        setFailedProjectKnowledgeUploads(failures);
      }
      if (failures.length || skippedFiles.length) {
        const summary = [
          uploaded.length ? `${uploaded.length} 份资料已上传` : "",
          failures.length ? `${failures.length} 份失败` : "",
          skippedFiles.length ? `${skippedFiles.length} 份同名文件已跳过` : "",
        ].filter(Boolean).join("，");
        setProjectKnowledgeError(`${summary}。`);
      }
    } catch (reason) {
      setProjectKnowledgeError(reason instanceof Error ? reason.message : "项目资料上传失败。");
    } finally {
      setProjectKnowledgeLoading(false);
      setProjectKnowledgeUploadProgress(null);
    }
  }

  function retryFailedProjectKnowledgeUploads() {
    void uploadProjectKnowledge(failedProjectKnowledgeUploads.map((failure) => failure.file));
  }

  async function deleteProjectKnowledge(documentIds: number[]) {
    const availableIds = new Set(projectKnowledgeDocuments.map((document) => document.id));
    const ids = [...new Set(documentIds)].filter((documentId) => availableIds.has(documentId));
    if (!ids.length) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 份项目资料吗？删除后将不能用于后续检索。`)) return;
    setProjectKnowledgeLoading(true);
    setProjectKnowledgeError(null);
    try {
      const deletedIds: number[] = [];
      const failures: string[] = [];
      for (const documentId of ids) {
        try {
          await deleteProjectKnowledgeDocument(documentId);
          deletedIds.push(documentId);
        } catch (reason) {
          failures.push(reason instanceof Error ? reason.message : "删除失败");
        }
      }
      if (deletedIds.length) {
        const deletedIdSet = new Set(deletedIds);
        setProjectKnowledgeDocuments((current) => current.filter((document) => !deletedIdSet.has(document.id)));
        setSelectedProjectKnowledgeIds((current) => current.filter((id) => !deletedIdSet.has(id)));
      }
      if (failures.length) {
        setProjectKnowledgeError(`${deletedIds.length} 份资料已删除，${failures.length} 份删除失败。`);
      }
    } finally {
      setProjectKnowledgeLoading(false);
    }
  }

  async function deleteSession(sessionId: string) {
    const session = sessions.find((item) => item.id === sessionId);
    if (!window.confirm(`删除会话“${session?.title || "简历定向优化"}”？会话中的消息、建议和事件将一并删除。`)) return;
    setDeletingSessionId(sessionId);
    setError("");
    try {
      await resumeAdvisorApi.deleteSession(sessionId);
      if (sessionId === selectedSessionId) setSelectedSessionId(null);
      await refreshLists();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除会话失败。");
    } finally {
      setDeletingSessionId(null);
    }
  }

  async function sendMessage(content: string, messageKind: "text" | "fact" = "text", remember = false) {
    if (!selectedSessionId) return;
    setError("");
    try {
      const result = await resumeAdvisorApi.postMessage(selectedSessionId, content, newClientMessageId(), messageKind, remember);
      if (result.run) {
        setSnapshot((current) => current ? { ...current, run: result.run || current.run, messages: [...current.messages, result.message] } : current);
        setLiveState({ runId: result.run.id, active: true, title: "消息已提交，等待 GPT 首 token", detail: "专用 Advisor worker 正在处理", liveText: "", cacheLabel: "", providerCacheLabel: "", firstTokenMs: null });
      } else {
        await refreshSnapshot(selectedSessionId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "消息发送失败。");
      throw reason;
    }
  }

  async function actOnSuggestion(suggestionId: string, action: "accepted" | "rejected" | "needs_revision" | "applied" | "restore", feedback = "") {
    setError("");
    try {
      await resumeAdvisorApi.actOnSuggestion(suggestionId, action, feedback);
      if (selectedSessionId) await refreshSnapshot(selectedSessionId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "建议操作失败。");
    }
  }

  async function finishSession() {
    if (!selectedSessionId) return;
    setError("");
    try {
      await resumeAdvisorApi.finish(selectedSessionId);
      await Promise.all([refreshSnapshot(selectedSessionId), refreshLists()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "结束会话失败。");
    }
  }

  async function cancelActiveRun() {
    if (!selectedSessionId || !activeRunId) return;
    setCancellingRunId(activeRunId);
    setError("");
    try {
      await resumeAdvisorApi.cancelRun(selectedSessionId, activeRunId);
      setLiveState((current) => current?.runId === activeRunId ? { ...current, active: false, title: "本轮运行已取消", detail: "不会继续写入新的建议" } : current);
      await Promise.all([refreshSnapshot(selectedSessionId), refreshLists(), refreshSloDashboard()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消本轮运行失败。");
    } finally {
      setCancellingRunId(null);
    }
  }

  const suggestions = useMemo(() => snapshot?.suggestions || [], [snapshot?.suggestions]);
  function focusSuggestion(suggestion: ResumeSuggestion) {
    setActiveBlockId(suggestion.target.blockId);
  }

  return (
    <main className="resume-advisor-page">
      <header className="resume-advisor-header">
        <div>
          <p className="eyebrow">RESUME ADVISOR</p>
          <h1>简历定向优化</h1>
          <p>逐段讨论、核验证据、复制后由你手动修改原简历。</p>
          {!projectKnowledgeLoading && projectKnowledgeDocuments.length === 0 && (
            <p className="resume-advisor-knowledge-callout" role="status">
              <strong>第一步：先上传项目资料库</strong>
              点击右侧“项目资料库”批量上传项目经历，再填写 JD 开始优化；系统会用这些资料检索可用的项目证据。
            </p>
          )}
        </div>
        <div className="resume-advisor-header-meta">
          {selectedSession && <div className="resume-advisor-session-state">会话状态：{selectedSession.sessionStatus}</div>}
          <AdvisorSloPanel dashboard={sloDashboard} />
          <ProjectKnowledgePanel
            documents={projectKnowledgeDocuments}
            selectedIds={selectedProjectKnowledgeIds}
            onSelectionChange={setSelectedProjectKnowledgeIds}
            isLoading={projectKnowledgeLoading}
            error={projectKnowledgeError}
            uploadProgress={projectKnowledgeUploadProgress}
            failedUploads={failedProjectKnowledgeUploads.map((failure) => ({ fileName: failure.file.name, message: failure.message }))}
            onUpload={(files) => void uploadProjectKnowledge(files)}
            onRetryFailedUploads={retryFailedProjectKnowledgeUploads}
            onDeleteSelected={(documentIds) => void deleteProjectKnowledge(documentIds)}
            disabled={starting || isWaitingForAgent}
          />
        </div>
      </header>
      {error && <p className="resume-advisor-error" role="alert">{error}</p>}
      <section className="resume-advisor-grid">
        <SessionSidebar
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          onSelect={(sessionId) => { setLiveState(null); setSelectedSessionId(sessionId); }}
          resumes={resumes}
          selectedResumeId={selectedResumeId}
          onResumeChange={setSelectedResumeId}
          jdText={jdText}
          onJdTextChange={setJdText}
          onStart={() => void startSession()}
          starting={starting}
          onUpload={(file) => void uploadResume(file)}
          uploading={uploading}
          onDeleteResume={(resumeId) => void deleteResume(resumeId)}
          deletingResumeId={deletingResumeId}
          onDeleteSession={(sessionId) => void deleteSession(sessionId)}
          deletingSessionId={deletingSessionId}
        />
        <section className="resume-advisor-main">
          <AgentTimeline events={snapshot?.events || []} />
          <ConversationThread
            messages={snapshot?.messages || []}
            streamingContent={liveState?.runId === activeRunId ? liveState.liveText : ""}
            facts={snapshot?.facts || []}
          />
          <AgentActivityBar activity={liveState ? {
            active: liveState.active,
            title: liveState.title,
            detail: liveState.detail,
            cacheLabel: liveState.cacheLabel,
            providerCacheLabel: liveState.providerCacheLabel,
            firstTokenMs: liveState.firstTokenMs,
          } : isWaitingForAgent ? { active: true, title: "等待 GPT 首 token" } : null} />
          {["QUEUED", "RUNNING", "PAUSED"].includes(activeRunStatus) && <button type="button" className="resume-advisor-danger-button resume-advisor-cancel-run" onClick={() => void cancelActiveRun()} disabled={cancellingRunId === activeRunId}>取消本轮运行</button>}
          {readyToFinish && <div className="resume-advisor-finish"><strong>已完成当前可验证的检查。</strong><button type="button" className="primary" onClick={() => void finishSession()}>我满意了，结束本次优化</button></div>}
          <MessageComposer onSend={sendMessage} disabled={!selectedSessionId || isClosed} />
        </section>
        <SuggestionWorkspace
          suggestions={suggestions}
          onSuggestionAction={actOnSuggestion}
          onFocusSuggestion={focusSuggestion}
          facts={snapshot?.facts || []}
        />
        <OriginalResumeViewer
          blocks={blocks}
          activeBlockId={activeBlockId}
          preview={preview}
          fileUrl={selectedSessionId ? `/api/agent/resume/sessions/${encodeURIComponent(selectedSessionId)}/resume-file` : ""}
        />
      </section>
    </main>
  );
}
