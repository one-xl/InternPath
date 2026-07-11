import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { AppShell } from "./components/layout/AppShell";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import { useHistory } from "./hooks/useHistory";
import { useJobAnalysis } from "./hooks/useJobAnalysis";
import { useModelConfigs } from "./hooks/useModelConfigs";
import { useProfile } from "./hooks/useProfile";
import { useResumeUpload } from "./hooks/useResumeUpload";
import { useAnalysisDrafts } from "./hooks/useAnalysisDrafts";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewAnalysisPage } from "./pages/NewAnalysisPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ResultPage } from "./pages/ResultPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LoginPage } from "./pages/LoginPage";
import { AdminPage } from "./pages/AdminPage";
import { ResumeAdvisorPage } from "./pages/ResumeAdvisorPage";
import { createEmptyDraft } from "./services/mockAnalysis";
import type { ApplicationStatus, HistoryRecord } from "./types/analysis";
import type { JobDraft } from "./types/job";
import type { PageKey } from "./types/navigation";
import type { AnalysisDraft } from "./types/analysisDraft";
import { safeUUID } from "./utils/uuid";

function toHistoryRecord(result: Omit<HistoryRecord, "status">, status: ApplicationStatus): HistoryRecord {
  return { ...result, status };
}

function normalizeDraft(draft: JobDraft): JobDraft {
  return { ...createEmptyDraft(), ...draft };
}

export default function App() {
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const [draft, setDraft] = useState<JobDraft>(() => createEmptyDraft());

  // Track draft context
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const [draftSaveMessage, setDraftSaveMessage] = useState<string | null>(null);

  // Authentication State
  const [currentUser, setCurrentUser] = useState<{ id: any; username: string; role?: string; generation_limit?: number } | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const currentUserRef = useRef(currentUser);
  const authExpiredAlertShownRef = useRef(false);

  useEffect(() => {
    currentUserRef.current = currentUser;
    if (currentUser) {
      authExpiredAlertShownRef.current = false;
    }
  }, [currentUser]);

  // 1. Session check on mount
  useEffect(() => {
    async function checkSession() {
      try {
        const response = await fetch("/api/me");
        if (response.ok) {
          const user = await response.json();
          setCurrentUser({ id: user.id, username: user.username, role: user.role, generation_limit: user.generation_limit });
        } else {
          setCurrentUser(null);
        }
      } catch {
        setCurrentUser(null);
      } finally {
        setCheckingAuth(false);
      }
    }
    checkSession();
  }, []);

  // 2. Global 401/403 response interceptor
  useEffect(() => {
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      const urlStr = typeof args[0] === 'string' ? args[0] : (args[0] as any)?.url || '';
      const isAuthEndpoint = urlStr.includes("/api/auth/login") || urlStr.includes("/api/auth/register") || urlStr.includes("/api/me") || urlStr.includes("/api/models/");
      if (response.status === 401 && !isAuthEndpoint) {
        const shouldNotify = currentUserRef.current && !authExpiredAlertShownRef.current;
        authExpiredAlertShownRef.current = true;
        setCurrentUser(null);
        setActivePage("dashboard");
        if (shouldNotify) {
          window.setTimeout(() => alert("登录状态已过期，请重新登录。"), 0);
        }
      }
      if (response.status === 403 && !isAuthEndpoint) {
        console.warn("你没有权限访问该资源。");
      }
      return response;
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  // 3. Logout action
  async function handleLogout() {
    if (window.confirm("确定要退出登录吗？")) {
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } catch (err) {
        console.error("Logout request failed:", err);
      } finally {
        // Clear all local storage cache keys (UI preferences only, not authoritative data)
        localStorage.removeItem("internpath.history.v2");
        localStorage.removeItem("job-desk:model-configs");
        localStorage.removeItem("internpath.profile.v2");
        localStorage.removeItem("internpath.profile");
        localStorage.removeItem("job-desk:drafts");
        localStorage.removeItem("job-desk:analysis-drafts");
        localStorage.removeItem("job-desk:active-configs");
        sessionStorage.removeItem("closed_session_announcements");

        setCurrentUser(null);
        setActivePage("dashboard");
        alert("已退出登录");
        window.location.reload();
      }
    }
  }

  const { profile, saveProfile, savedAt } = useProfile();
  const analysis = useJobAnalysis();
  const resumeUpload = useResumeUpload();
  const isAuthenticated = Boolean(currentUser);
  const modelConfigs = useModelConfigs(isAuthenticated);
  const history = useHistory(isAuthenticated);
  const draftsControl = useAnalysisDrafts(isAuthenticated);

  // Prevent accidental refresh/close during ongoing analysis
  useEffect(() => {
    if (!analysis.isAnalyzing) return;

    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "正在进行岗位分析，刷新或关闭页面将中断当前分析进度，确定离开吗？";
      return e.returnValue;
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [analysis.isAnalyzing]);

  const activeSavedRecord = useMemo(
    () => history.records.find((record) => record.id === analysis.result?.id),
    [analysis.result?.id, history.records],
  );

  function updateDraft(patch: Partial<JobDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  async function runAnalysis() {
    setDraftSaveMessage(null);

    if (currentUser && currentUser.role !== "admin") {
      if (currentUser.generation_limit !== undefined && currentUser.generation_limit <= 0) {
        alert("您的账号生成额度已用尽，请联系管理员增加次数。");
        return;
      }
    }

    // 1. Auto-create/save draft if not already working on an active draft
    let draftId = activeDraftId;
    if (!draftId && draft.jdText?.trim() && resumeUpload.resumeFile) {
      try {
        const saved = draftsControl.saveDraft({
          companyName: draft.company,
          jobTitle: draft.title,
          jdText: draft.jdText,
          targetType: draft.targetType,
          jobDirection: draft.jobDirection,
          notes: draft.candidateMaterial,
          link: draft.link,
          location: draft.location,
          workMode: draft.workMode,
          level: draft.level,
          resumeFile: resumeUpload.resumeFile,
          parsedResume: resumeUpload.parsedResume,
          embeddingConfigId: modelConfigs.activeEmbeddingConfig?.id,
          chatConfigId: modelConfigs.activeChatConfig?.id,
        });
        draftId = saved.id;
        setActiveDraftId(draftId);
      } catch (err) {
        console.error("Auto-creating draft failed on start:", err);
      }
    }

    // Save active session to localStorage for reload survival
    try {
      const session = {
        draft,
        resumeFile: resumeUpload.resumeFile,
        parsedResume: resumeUpload.parsedResume,
        activeDraftId: draftId,
        timestamp: Date.now(),
      };
      localStorage.setItem("internpath:active-analysis-session", JSON.stringify(session));
    } catch (e) {
      console.warn("Failed to write active analysis session to localStorage:", e);
    }

    // Check for cached vector result from a previous failed run of the same draft & configurations
    let vectorResultCache = undefined;
    const activeDraft = draftId ? draftsControl.drafts.find((d) => d.id === draftId) : null;
    if (activeDraft?.vectorResultCache) {
      const cache = activeDraft.vectorResultCache;
      const sameJd = activeDraft.jdText === draft.jdText;
      const sameResume = activeDraft.resumeFile?.id === resumeUpload.resumeFile?.id;
      const sameEmbedConfig = activeDraft.embeddingConfigId === modelConfigs.activeEmbeddingConfig?.id;

      if (sameJd && sameResume && sameEmbedConfig && cache.parsedJD && cache.retrievedChunks && cache.retrievedChunks.length > 0) {
        const reuse = window.confirm(
          "检测到上一次分析失败时的向量比对结果，且简历、JD 和向量模型未发生改变。是否直接跳过向量比对，开始大模型分析以节省时间？"
        );
        if (reuse) {
          vectorResultCache = cache;
        }
      }
    }

    const runResult = await analysis.runAnalysis({
      draft,
      resumeFile: resumeUpload.resumeFile,
      parsedResume: resumeUpload.parsedResume,
      chunks: resumeUpload.chunks,
      embeddingConfig: modelConfigs.activeEmbeddingConfig,
      chatConfig: modelConfigs.activeChatConfig,
      activeEmbeddingConfigId: modelConfigs.state.active.embeddingConfigId,
      activeChatConfigId: modelConfigs.state.active.chatConfigId,
      sourceDraftId: draftId || undefined,
      onSaveHistory: (res) => {
        history.saveRecord(toHistoryRecord(res, "watching"));
      },
      vectorResultCache
    });

    if (runResult.ok) {
      localStorage.removeItem("internpath:active-analysis-session");
      // Decrement limit in local state
      setCurrentUser((prev) => {
        if (prev && prev.role !== "admin" && prev.generation_limit !== undefined) {
          return { ...prev, generation_limit: Math.max(0, prev.generation_limit - 1) };
        }
        return prev;
      });
      // If successful, mark the draft as converted to history (completed status)
      if (draftId) {
        draftsControl.updateDraftStatus(draftId, "converted_to_history");
        setActiveDraftId(null);
      }
      setActivePage("result");
    } else {
      localStorage.removeItem("internpath:active-analysis-session");
      // Analysis failed! Auto-save the input fields and context as a failed draft.
      try {
        const failedStepId = runResult.failedStep || "validate";
        const errorMsg = runResult.errorMessage || "未知分析错误";

        const saved = draftsControl.saveFailedAnalysisDraft({
          id: draftId || undefined,
          companyName: draft.company,
          jobTitle: draft.title,
          jdText: draft.jdText,
          targetType: draft.targetType,
          jobDirection: draft.jobDirection,
          notes: draft.candidateMaterial,
          link: draft.link,
          location: draft.location,
          workMode: draft.workMode,
          level: draft.level,
          resumeFile: resumeUpload.resumeFile,
          parsedResume: resumeUpload.parsedResume,
          embeddingConfigId: modelConfigs.activeEmbeddingConfig?.id,
          chatConfigId: modelConfigs.activeChatConfig?.id,
          failedStep: failedStepId,
          errorMessage: errorMsg,
          progressSteps: analysis.steps,
          modelUsageSnapshot: {
            embeddingProvider: modelConfigs.activeEmbeddingConfig?.provider,
            embeddingModelId: modelConfigs.activeEmbeddingConfig?.modelId,
            chatProvider: modelConfigs.activeChatConfig?.provider,
            chatModelId: modelConfigs.activeChatConfig?.modelId,
          },
          vectorResultCache: runResult.partialResult ? {
            parsedJD: runResult.partialResult.parsedJD,
            retrievedChunks: runResult.partialResult.retrievedChunks,
            requirementMatches: runResult.partialResult.requirementMatches,
            hardConstraintsResult: runResult.partialResult.hardConstraintsResult,
          } : undefined,
        });

        setActiveDraftId(saved.id);
        setDraftSaveMessage("已自动保存为草稿，可稍后继续分析。");

        // Save a failed run history record
        const failedResult: Omit<HistoryRecord, "status"> = {
          id: saved.id,
          createdAt: new Date().toISOString(),
          draft: draft,
          sourceDraftId: saved.id,
          resumeFile: resumeUpload.resumeFile ? { ...resumeUpload.resumeFile, status: "error" } as any : undefined,
          parsedResume: resumeUpload.parsedResume || undefined,
          retrievedResumeChunks: [],
          retrievalSummary: `分析中断于: ${failedStepId}。原因: ${errorMsg}`,
          retrievalScore: 0,
          decision: "no",
          matchScore: 0,
          riskLevel: "high",
          priority: "P3",
          oneLineReason: `分析中断于【${failedStepId}】: ${errorMsg}`,
          detectedKeywords: [],
          missingKeywords: [],
          dimensions: [],
          resumeAdvice: [],
          learningSuggestions: [],
          nextActions: ["检查模型配置或网络连接", "点击继续分析重新开始"],
          citedResumeChunks: [],
          is_failed: true,
        };
        await history.saveRecord(toHistoryRecord(failedResult, "watching"));
      } catch (err: any) {
        console.error("[draft] Failed to auto-save draft:", err);
        setDraftSaveMessage("分析失败，且草稿保存失败。请手动复制当前 JD 或稍后重试。");
      }
    }
  }

  // Restore active analysis session on boot/login
  useEffect(() => {
    if (!currentUser) return;
    // Only attempt recovery when model configurations have loaded so that runAnalysis won't fail validation immediately.
    if (!modelConfigs.state.embeddingConfigs.length || !modelConfigs.state.chatConfigs.length) return;

    const sessionStr = localStorage.getItem("internpath:active-analysis-session");
    if (!sessionStr) return;

    try {
      const session = JSON.parse(sessionStr);
      // Valid within 30 minutes
      if (Date.now() - session.timestamp < 30 * 60 * 1000) {
        // Clear session immediately to avoid infinite recovery loops if runAnalysis fails
        localStorage.removeItem("internpath:active-analysis-session");

        const confirmRestore = window.confirm("检测到您有未完成的岗位分析，是否恢复并继续？");
        if (confirmRestore) {
          setDraft(normalizeDraft(session.draft));
          if (session.resumeFile || session.parsedResume) {
            resumeUpload.restoreResumeData(
              session.resumeFile || null,
              session.parsedResume || null,
              session.parsedResume?.chunks || []
            );
          }
          if (session.activeDraftId) {
            setActiveDraftId(session.activeDraftId);
          }
          // Shift view to new analysis page to show progress
          setActivePage("new");

          // Trigger the analysis after a short timeout so React state updates settle
          setTimeout(() => {
            void runAnalysis();
          }, 600);
        }
      } else {
        localStorage.removeItem("internpath:active-analysis-session");
      }
    } catch (e) {
      console.warn("Failed to restore active analysis session:", e);
      localStorage.removeItem("internpath:active-analysis-session");
    }
  }, [currentUser, modelConfigs.state.embeddingConfigs.length, modelConfigs.state.chatConfigs.length]);

  function startNewAnalysis() {
    setDraft(createEmptyDraft());
    analysis.setExistingResult(null);
    resumeUpload.reset();
    setActiveDraftId(null);
    setDraftSaveMessage(null);
    setActivePage("new");
  }

  function saveCurrent(status: ApplicationStatus = "watching") {
    if (!analysis.result) return;
    history.saveRecord(toHistoryRecord(analysis.result, status));
  }

  function openHistoryRecord(record: HistoryRecord) {
    analysis.setExistingResult(record);
    setDraft(normalizeDraft(record.draft));
    setActivePage("result");
  }

  function copyAdvice() {
    if (!analysis.result) return;
    const text = analysis.result.resumeAdvice
      .map((item) => `【${item.priority}】${item.issue}\n建议：${item.suggestion}\n示例：${item.example}`)
      .join("\n\n");
    void navigator.clipboard.writeText(text);
  }

  function markCurrent(status: ApplicationStatus) {
    if (!analysis.result) return;
    saveCurrent(status);
  }

  // --- Draft Handlers ---

  function handleSaveDraft() {
    const hasCompany = Boolean(draft.company?.trim());
    const hasTitle = Boolean(draft.title?.trim());
    const hasJd = Boolean(draft.jdText?.trim());
    const hasFile = Boolean(resumeUpload.resumeFile);

    if (!hasCompany && !hasTitle && !hasJd && !hasFile) {
      alert("当前没有可保存的内容。");
      return;
    }

    try {
      const saved = draftsControl.saveDraft({
        id: activeDraftId || undefined,
        companyName: draft.company,
        jobTitle: draft.title,
        jdText: draft.jdText,
        targetType: draft.targetType,
        jobDirection: draft.jobDirection,
        notes: draft.candidateMaterial,
        link: draft.link,
        location: draft.location,
        workMode: draft.workMode,
        level: draft.level,
        resumeFile: resumeUpload.resumeFile,
        parsedResume: resumeUpload.parsedResume,
        embeddingConfigId: modelConfigs.activeEmbeddingConfig?.id,
        chatConfigId: modelConfigs.activeChatConfig?.id,
      });
      setActiveDraftId(saved.id);
      alert("草稿已保存。");
    } catch (err: any) {
      alert(err.message || "草稿保存失败，请稍后重试。");
    }
  }

  function handleRestoreDraft(targetDraft: AnalysisDraft) {
    setDraft({
      company: targetDraft.companyName || "",
      title: targetDraft.jobTitle || "",
      link: targetDraft.link || "",
      location: targetDraft.location || "",
      workMode: targetDraft.workMode || "unknown",
      level: targetDraft.level || "unknown",
      jdText: targetDraft.jdText || "",
      targetType: targetDraft.targetType || "",
      jobDirection: targetDraft.jobDirection || "",
      candidateMaterial: targetDraft.notes || "",
      resumeText: "",
      projectText: "",
      skillsText: "",
      goalText: "",
      useDefaultProfile: false,
    });

    resumeUpload.restoreResumeData(
      targetDraft.resumeFile || null,
      targetDraft.parsedResume || null,
      targetDraft.parsedResume?.chunks || []
    );

    if (targetDraft.embeddingConfigId || targetDraft.chatConfigId) {
      let configMissing = false;
      if (targetDraft.embeddingConfigId) {
        const hasEmbed = modelConfigs.state.embeddingConfigs.some((c) => c.id === targetDraft.embeddingConfigId);
        if (hasEmbed) {
          modelConfigs.setActiveEmbeddingConfig(targetDraft.embeddingConfigId);
        } else {
          configMissing = true;
        }
      }
      if (targetDraft.chatConfigId) {
        const hasChat = modelConfigs.state.chatConfigs.some((c) => c.id === targetDraft.chatConfigId);
        if (hasChat) {
          modelConfigs.setActiveChatConfig(targetDraft.chatConfigId);
        } else {
          configMissing = true;
        }
      }

      if (configMissing) {
        alert("当前草稿引用的部分模型配置已不存在，请重新选择模型后再分析。");
      }
    }

    setActiveDraftId(targetDraft.id);
    setDraftSaveMessage(null);
    setActivePage("new");
    alert("已恢复草稿，可以继续编辑或开始分析。");
  }

  function handleCloneDraft(targetDraft: AnalysisDraft) {
    const cloned = {
      ...targetDraft,
      id: safeUUID(),
      companyName: `${targetDraft.companyName || "未名公司"} (副本)`,
      updatedAt: new Date().toISOString(),
      status: "draft" as const,
    };
    draftsControl.saveDraft(cloned);
    alert("已成功复制副本为新草稿！");
  }

  function handleClearForm() {
    if (window.confirm("确定要清空当前所有输入与已解析的简历文件吗？")) {
      setDraft(createEmptyDraft());
      resumeUpload.reset();
      setActiveDraftId(null);
      setDraftSaveMessage(null);
      analysis.resetProgress();
    }
  }

  const formError = analysis.error || resumeUpload.error;

  if (checkingAuth) {
    return (
      <div className="login-page-container" style={{ display: "flex", flexDirection: "column", gap: "16px", color: "#fff" }}>
        <div className="spinner" style={{ width: "40px", height: "40px" }}></div>
        <p style={{ fontSize: "14px", fontWeight: "600" }}>正在验证登录状态…</p>
      </div>
    );
  }

  if (!currentUser) {
    return <LoginPage onLoginSuccess={(user) => {
      sessionStorage.removeItem("closed_session_announcements");
      setCurrentUser(user);
    }} />;
  }

  return (
    <ErrorBoundary>
      <AppShell activePage={activePage} onNavigate={setActivePage} onLogout={handleLogout} userRole={currentUser?.role} generationLimit={currentUser?.generation_limit}>
        {activePage === "dashboard" && (
          <DashboardPage
            records={history.records}
            latestResult={analysis.result ?? history.records[0] ?? null}
            profile={profile}
            onNewAnalysis={startNewAnalysis}
            onOpenLatest={() => setActivePage("result")}
            onHistory={() => setActivePage("history")}
            onNavigate={setActivePage}
          />
        )}
        {activePage === "new" && (
          <NewAnalysisPage
            draft={draft}
            resumeFile={resumeUpload.resumeFile}
            parsedResume={resumeUpload.parsedResume}
            resumeStatus={resumeUpload.status}
            resumeError={resumeUpload.error}
            resumeReady={resumeUpload.isReady}
            isAnalyzing={analysis.isAnalyzing}
            isRetrieving={analysis.analysisStatus === "retrieving"}
            activeEmbeddingConfig={modelConfigs.activeEmbeddingConfig}
            activeChatConfig={modelConfigs.activeChatConfig}
            progressStep={analysis.progressStep}
            steps={analysis.steps}
            analysisStatus={analysis.analysisStatus}
            error={formError}
            onChangeDraft={updateDraft}
            onSelectResume={resumeUpload.selectFile}
            onSelectSavedResume={resumeUpload.selectSavedResume}
            onRetryResume={resumeUpload.retry}
            onRemoveResume={resumeUpload.removeFile}
            onGoSettings={() => setActivePage("settings")}
            onAnalyze={runAnalysis}

            latestDraft={draftsControl.latestDraft}
            draftSaveMessage={draftSaveMessage}
            onRestoreDraft={handleRestoreDraft}
            onDeleteDraft={draftsControl.deleteDraft}
            onSaveDraft={handleSaveDraft}
            onViewDrafts={() => setActivePage("history")}
            onClearForm={handleClearForm}
          />
        )}
        {activePage === "result" && (
          <ResultPage
            result={analysis.result}
            isSaved={Boolean(activeSavedRecord)}
            onNewAnalysis={startNewAnalysis}
            onSave={() => saveCurrent("watching")}
            onCopyAdvice={copyAdvice}
            onMarkApplied={() => markCurrent("applied")}
            onAbandon={() => markCurrent("abandoned")}
            onUpdateResult={analysis.setExistingResult}
            onOpenResumeAdvisor={(context) => {
              sessionStorage.setItem("internpath:resume-advisor-launch", JSON.stringify(context));
              setActivePage("agent-resume");
            }}
          />
        )}
        {activePage === "history" && (
          <HistoryPage
            records={history.filteredRecords}
            query={history.query}
            filter={history.filter}
            sort={history.sort}
            onQueryChange={history.setQuery}
            onFilterChange={history.setFilter}
            onSortChange={history.setSort}
            onOpen={openHistoryRecord}
            onDelete={history.deleteRecord}
            onStatusChange={history.updateStatus}
            onNewAnalysis={startNewAnalysis}

            drafts={draftsControl.drafts}
            onRestoreDraft={handleRestoreDraft}
            onCloneDraft={handleCloneDraft}
            onDeleteDraft={draftsControl.deleteDraft}
          />
        )}
        {activePage === "profile" && <ProfilePage profile={profile} savedAt={savedAt} onSave={saveProfile} />}
        {activePage === "settings" && (
          <SettingsPage
            state={modelConfigs.state}
            activeEmbeddingConfig={modelConfigs.activeEmbeddingConfig}
            activeChatConfig={modelConfigs.activeChatConfig}
            onSaveEmbedding={modelConfigs.saveEmbeddingConfig}
            onSaveChat={modelConfigs.saveChatConfig}
            onDeleteEmbedding={modelConfigs.deleteEmbeddingConfig}
            onDeleteChat={modelConfigs.deleteChatConfig}
            onSetActiveEmbedding={modelConfigs.setActiveEmbeddingConfig}
            onSetActiveChat={modelConfigs.setActiveChatConfig}
            onTestEmbedding={modelConfigs.testEmbeddingConfig}
            onTestChat={modelConfigs.testChatConfig}
            onClearAll={modelConfigs.clearAllConfigs}
          />
        )}
        {activePage === "admin" && currentUser?.role === "admin" && (
          <AdminPage />
        )}
        {activePage === "agent-resume" && (
          <ResumeAdvisorPage />
        )}
      </AppShell>
    </ErrorBoundary>
  );
}
