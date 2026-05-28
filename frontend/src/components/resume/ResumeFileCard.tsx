import { useState } from "react";
import type { ParsedResume, UploadedResumeFile } from "../../types/resume";
import { formatDateTime } from "../../utils/format";
import { formatFileSize } from "../../utils/fileValidation";
import { Button } from "../ui/Button";
import { ResumeParseStatus } from "./ResumeParseStatus";

interface ResumeFileCardProps {
  file: UploadedResumeFile;
  parsedResume: ParsedResume | null;
  error: string;
  onRetry: () => void;
  onRemove: () => void;
}

export function ResumeFileCard({ file, parsedResume, error, onRetry, onRemove }: ResumeFileCardProps) {
  const [showChunksDetail, setShowChunksDetail] = useState(false);
  const profile = parsedResume?.extractedProfile;

  const chunksList = parsedResume && Array.isArray(parsedResume.chunks) ? parsedResume.chunks : [];

  const uniqueSectionsCount = new Set(
    chunksList.map((c) => c.sectionTitle || c.section || c.sectionId || "generic")
  ).size;

  return (
    <div className="resume-file-card">
      <div className="resume-file-main">
        <div>
          <span className="section-kicker">当前简历</span>
          <h3>{file.name}</h3>
          <p>
            {file.type || "未知类型"} · {formatFileSize(file.size)} · {formatDateTime(file.uploadedAt)}
          </p>
        </div>
        <ResumeParseStatus status={file.status} />
      </div>

      {error && <p className="resume-error">{error}</p>}

      {parsedResume && (
        <>
          <div className="resume-summary-grid">
            <div>
              <strong>{profile?.skills?.length ?? 0}</strong>
              <span>识别技能</span>
            </div>
            <div>
              <strong>{profile?.projects?.length ?? 0}</strong>
              <span>项目经历</span>
            </div>
            <div>
              <strong>{profile?.education?.length ?? 0}</strong>
              <span>教育经历</span>
            </div>
            <div>
              <strong>{profile?.experiences?.length ?? 0}</strong>
              <span>工作/实习</span>
            </div>
            <div>
              <strong>{chunksList.length}</strong>
              <span>检索片段</span>
            </div>
          </div>

          {chunksList.length > 0 && (
            <div style={{ marginTop: "16px", borderTop: "1px solid var(--line)", paddingTop: "16px" }}>
              <button
                type="button"
                onClick={() => setShowChunksDetail(!showChunksDetail)}
                style={{
                  background: "rgba(255, 255, 255, 0.05)",
                  color: "var(--text-light)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: "8px 12px",
                  width: "100%",
                  textAlign: "left",
                  fontSize: "13px",
                  fontWeight: "600",
                  cursor: "pointer",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center"
                }}
              >
                <span>📂 知识库解析详情 ({uniqueSectionsCount} 个 Section / {chunksList.length} 个片段)</span>
                <span>{showChunksDetail ? "收起 ▲" : "展开 ▼"}</span>
              </button>
              
              {showChunksDetail && (
                <div style={{ marginTop: "12px", maxHeight: "300px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "10px", padding: "10px", background: "rgba(0,0,0,0.02)", borderRadius: "var(--radius-sm)" }}>
                  {chunksList.map((chunk) => {
                    const hierarchyPath = chunk.hierarchy?.join(" > ") || chunk.sectionTitle || chunk.section || "未命名 Section";
                  const sectionImportance = chunk.importance !== undefined ? chunk.importance : (chunk.metadata?.importance ?? 0.60);
                  const semType = chunk.semanticType || chunk.metadata?.semanticType || "generic";
                  
                  return (
                    <div key={chunk.id} style={{ padding: "10px", background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "6px", fontSize: "12.5px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px", flexWrap: "wrap", gap: "6px" }}>
                        <span style={{ fontWeight: "700", color: "var(--text)" }}>
                          📍 {hierarchyPath}
                        </span>
                        <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                          <span style={{ background: "rgba(16, 185, 129, 0.12)", color: "#10b981", fontSize: "10px", padding: "2px 6px", borderRadius: "4px", fontWeight: "600" }}>
                            {semType}
                          </span>
                          <span style={{ background: "rgba(245, 158, 11, 0.12)", color: "#f59e0b", fontSize: "10px", padding: "2px 6px", borderRadius: "4px", fontWeight: "600" }}>
                            ⭐ 权重: {sectionImportance.toFixed(2)}
                          </span>
                        </div>
                      </div>
                      <p style={{ color: "var(--muted)", margin: "0 0 6px 0", lineHeight: "1.4" }}>
                        {chunk.content}
                      </p>
                      {chunk.keywords && chunk.keywords.length > 0 && (
                        <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                          {chunk.keywords.slice(0, 5).map(kw => (
                            <span key={kw} style={{ background: "var(--line)", color: "var(--text-light)", fontSize: "9px", padding: "1px 4px", borderRadius: "2px" }}>
                              {kw}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </>
    )}

      <div className="resume-card-actions">
        {file.status === "failed" && (
          <Button type="button" variant="secondary" onClick={onRetry}>
            重试解析
          </Button>
        )}
        <Button type="button" variant="ghost" onClick={onRemove}>
          移除文件
        </Button>
      </div>
    </div>
  );
}
