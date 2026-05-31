import type { DragEvent } from "react";
import { useRef, useState } from "react";
import type { ParsedResume, ResumeFileStatus, UploadedResumeFile } from "../../types/resume";
import { RESUME_MAX_FILE_SIZE, formatFileSize } from "../../utils/fileValidation";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ResumeFileCard } from "./ResumeFileCard";
import { ResumeParseStatus } from "./ResumeParseStatus";
import {
  fetchSavedResumes,
  fetchSavedResume,
  deleteSavedResume,
  type SavedResume
} from "../../services/resumeService";

interface ResumeUploadProps {
  resumeFile: UploadedResumeFile | null;
  parsedResume: ParsedResume | null;
  status: ResumeFileStatus;
  error: string;
  disabled?: boolean;
  onSelectFile: (file: File) => void;
  onSelectSavedResume: (parsed: ParsedResume) => void;
  onRetry: () => void;
  onRemove: () => void;
}

export function ResumeUpload({
  resumeFile,
  parsedResume,
  status,
  error,
  disabled,
  onSelectFile,
  onSelectSavedResume,
  onRetry,
  onRemove,
}: ResumeUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  
  // History selection state
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [historyResumes, setHistoryResumes] = useState<SavedResume[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState("");

  function chooseFile() {
    inputRef.current?.click();
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files.item(0);
    if (file) onSelectFile(file);
  }

  async function openHistory() {
    setShowHistoryModal(true);
    setIsLoadingHistory(true);
    setHistoryError("");
    try {
      const list = await fetchSavedResumes();
      setHistoryResumes(list);
    } catch (err: any) {
      setHistoryError(err.message || "加载历史简历失败");
    } finally {
      setIsLoadingHistory(false);
    }
  }

  async function handleSelectSavedResume(id: string) {
    setShowHistoryModal(false);
    try {
      const parsed = await fetchSavedResume(id);
      onSelectSavedResume(parsed);
    } catch (err: any) {
      alert(err.message || "获取简历内容失败");
    }
  }

  async function handleDeleteSavedResume(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    if (!window.confirm("确定要删除这份历史简历吗？")) return;
    try {
      await deleteSavedResume(id);
      setHistoryResumes((prev) => prev.filter((r) => r.id !== id));
    } catch (err: any) {
      alert(err.message || "删除失败");
    }
  }

  return (
    <Card
      title="上传简历文件"
      description="支持 PDF、DOC、DOCX 格式。系统会解析你的简历内容，并结合岗位 JD 检索最相关的经历进行分析。"
    >
      <div
        className={`resume-dropzone ${isDragging ? "dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onSelectFile(file);
            event.currentTarget.value = "";
          }}
        />
        <div>
          <ResumeParseStatus status={status} />
          <h3>{resumeFile ? "已选择简历文件" : "等待上传简历"}</h3>
          <p>点击选择或拖拽文件到这里。文件大小不能超过 {formatFileSize(RESUME_MAX_FILE_SIZE)}。</p>
        </div>
        <div style={{ display: "flex", gap: "10px", justifyContent: "center" }}>
          <Button type="button" variant="primary" onClick={chooseFile} disabled={disabled}>
            {resumeFile ? "重新上传" : "选择文件"}
          </Button>
          <Button type="button" variant="secondary" onClick={openHistory} disabled={disabled}>
            从已转换简历中选择
          </Button>
        </div>
      </div>

      <p className="privacy-note">
        你的简历可能包含手机号、邮箱、教育经历等敏感信息。当前版本优先在本地解析和保存数据，系统会安全且持久地存储您的向量化解析副本，以便您快速复用。
      </p>

      {resumeFile && (
        <ResumeFileCard file={resumeFile} parsedResume={parsedResume} error={error} onRetry={onRetry} onRemove={onRemove} />
      )}

      {/* History modal */}
      {showHistoryModal && (
        <div className="history-modal-overlay">
          <div className="history-modal-panel">
            <div className="history-modal-header">
              <h3 className="history-modal-title">📁 已保存的已转换简历列表</h3>
              <button
                type="button"
                onClick={() => setShowHistoryModal(false)}
                className="history-modal-close"
              >
                ✕
              </button>
            </div>

            {historyError && (
              <div className="history-modal-error">
                {historyError}
              </div>
            )}

            <div className="history-resume-list">
              {isLoadingHistory ? (
                <div className="history-modal-loading">加载中...</div>
              ) : historyResumes.length === 0 ? (
                <div className="history-modal-empty">暂无已转换的简历记录</div>
              ) : (
                historyResumes.map((res) => (
                  <div
                    key={res.id}
                    onClick={() => handleSelectSavedResume(res.id)}
                    className="history-resume-item"
                  >
                    <div className="history-resume-info">
                      <span className="history-resume-name">{res.name}</span>
                      <span className="history-resume-meta">
                        大小: {formatFileSize(res.size)} | 时间: {res.createdAt ? new Date(res.createdAt).toLocaleString("zh-CN") : "未知"}
                      </span>
                    </div>
                    <div className="history-resume-actions">
                      <span className="history-resume-select-label">点击选择</span>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteSavedResume(res.id, e)}
                        className="history-resume-delete-btn"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="history-modal-footer">
              <Button type="button" variant="secondary" onClick={() => setShowHistoryModal(false)}>
                关闭
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
