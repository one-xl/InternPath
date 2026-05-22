import { useMemo, useState, useEffect, useRef } from "react";
import { AppShell } from "./components/layout/AppShell";
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
  const [currentUser, setCurrentUser] = useState<{ id: number; username: string } | null>(null);
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
          setCurrentUser({ id: user.id, username: user.username });
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
      const isAuthEndpoint = urlStr.includes("/api/auth/login") || urlStr.includes("/api/auth/register") || urlStr.includes("/api/me");
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

  const activeSavedRecord = useMemo(
    () => history.records.find((record) => record.id === analysis.result?.id),
    [analysis.result?.id, history.records],
  );

  function updateDraft(patch: Partial<JobDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  async function runAnalysis() {
    setDraftSaveMessage(null);
    const runResult = await analysis.runAnalysis({
      draft,
      resumeFile: resumeUpload.resumeFile,
      parsedResume: resumeUpload.parsedResume,
      chunks: resumeUpload.chunks,
      embeddingConfig: modelConfigs.activeEmbeddingConfig,
      chatConfig: modelConfigs.activeChatConfig,
      activeEmbeddingConfigId: modelConfigs.state.active.embeddingConfigId,
      activeChatConfigId: modelConfigs.state.active.chatConfigId,
      sourceDraftId: activeDraftId || undefined,
      onSaveHistory: (res) => {
        history.saveRecord(toHistoryRecord(res, "watching"));
      }
    });

    if (runResult.ok) {
      // If successful, and we are working from a draft, mark the draft as converted to history
      if (activeDraftId) {
        draftsControl.updateDraftStatus(activeDraftId, "converted_to_history");
        setActiveDraftId(null);
      }
      setActivePage("result");
    } else {
      // Analysis failed! Auto-save the input fields and context as a failed draft.
      try {
        const failedStepId = runResult.failedStep || "validate";
        const errorMsg = runResult.errorMessage || "未知分析错误";

        const saved = draftsControl.saveFailedAnalysisDraft({
          id: activeDraftId || undefined,
          companyName: draft.company,
          jobTitle: draft.title,
          jdText: draft.jdText,
          targetType: draft.targetType,
          jobDirection: draft.jobDirection,
          notes: draft.candidateMaterial,
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
        });

        setActiveDraftId(saved.id);
        setDraftSaveMessage("已自动保存为草稿，可稍后继续分析。");
      } catch (err: any) {
        console.error("[draft] Failed to auto-save draft:", err);
        setDraftSaveMessage("分析失败，且草稿保存失败。请手动复制当前 JD 或稍后重试。");
      }
    }
  }

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
      link: "",
      location: "",
      workMode: "unknown",
      level: "unknown",
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
    return <LoginPage onLoginSuccess={(user) => setCurrentUser(user)} />;
  }

  return (
    <AppShell activePage={activePage} onNavigate={setActivePage} onLogout={handleLogout}>
      {activePage === "dashboard" && (
        <DashboardPage
          records={history.records}
          latestResult={analysis.result ?? history.records[0] ?? null}
          profile={profile}
          onNewAnalysis={startNewAnalysis}
          onOpenLatest={() => setActivePage("result")}
          onHistory={() => setActivePage("history")}
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
          onTestEmbedding={(config) => void modelConfigs.testEmbeddingConfig(config)}
          onTestChat={(config) => void modelConfigs.testChatConfig(config)}
          onClearAll={modelConfigs.clearAllConfigs}
        />
      )}
    </AppShell>
  );
}
