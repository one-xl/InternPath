import type { AdvisorSession, ResumeSummary } from "./types";

export function SessionSidebar({
  sessions,
  selectedSessionId,
  onSelect,
  resumes,
  selectedResumeId,
  onResumeChange,
  jdText,
  onJdTextChange,
  onStart,
  starting,
  onUpload,
  uploading,
  onDeleteResume,
  deletingResumeId,
  onDeleteSession,
  deletingSessionId,
}: {
  sessions: AdvisorSession[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  resumes: ResumeSummary[];
  selectedResumeId: string;
  onResumeChange: (resumeId: string) => void;
  jdText: string;
  onJdTextChange: (value: string) => void;
  onStart: () => void;
  starting: boolean;
  onUpload: (file: File) => void;
  uploading: boolean;
  onDeleteResume: (resumeId: string) => void;
  deletingResumeId: string | null;
  onDeleteSession: (sessionId: string) => void;
  deletingSessionId: string | null;
}) {
  const selectedResume = resumes.find((resume) => resume.id === selectedResumeId);

  return (
    <aside className="resume-advisor-sidebar">
      <h2>开始新会话</h2>
      <label>
        简历版本
        <select value={selectedResumeId} onChange={(event) => onResumeChange(event.target.value)}>
          <option value="">请选择简历</option>
          {resumes.map((resume) => (
            <option key={resume.id} value={resume.id}>
              {resume.name}{resume.versionNo ? ` · v${resume.versionNo}` : ""}
            </option>
          ))}
        </select>
      </label>
      <div className="resume-advisor-resume-actions">
        <button
          type="button"
          className="resume-advisor-danger-button"
          aria-label={`删除所选简历：${selectedResume?.name || "当前简历"}`}
          disabled={!selectedResumeId || deletingResumeId === selectedResumeId}
          onClick={() => onDeleteResume(selectedResumeId)}
        >
          {deletingResumeId === selectedResumeId ? "正在删除简历…" : "删除所选简历"}
        </button>
      </div>
      <label className="resume-advisor-upload">
        上传新的简历版本
        <input
          type="file"
          accept=".pdf,.docx,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={uploading}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.currentTarget.value = "";
          }}
        />
        <span>{uploading ? "正在解析并建立新版本…" : "PDF、DOCX 或 TXT，最大 10MB"}</span>
      </label>
      <label>
        目标岗位 JD
        <textarea value={jdText} onChange={(event) => onJdTextChange(event.target.value)} rows={7} placeholder="粘贴目标岗位描述" />
      </label>
      <button type="button" className="primary" disabled={starting || !selectedResumeId || !jdText.trim()} onClick={onStart}>
        {starting ? "正在建立会话…" : "开始分析"}
      </button>

      <div className="resume-advisor-session-list">
        <h2>历史会话</h2>
        <div className="resume-advisor-session-items">
          {sessions.map((session) => (
            <div className="resume-advisor-session-row" key={session.id}>
              <button
                type="button"
                className={`resume-advisor-session-button${session.id === selectedSessionId ? " selected" : ""}`}
                onClick={() => onSelect(session.id)}
              >
                <strong>{session.title || "简历定向优化"}</strong>
                <span>{session.sessionStatus === "SATISFIED" ? "已满意结束" : session.sessionStatus}</span>
              </button>
              <button
                type="button"
                className="resume-advisor-danger-button resume-advisor-delete-session"
                aria-label={`删除会话：${session.title || "简历定向优化"}`}
                disabled={deletingSessionId === session.id}
                onClick={() => onDeleteSession(session.id)}
              >
                {deletingSessionId === session.id ? "删除中…" : "删除"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
