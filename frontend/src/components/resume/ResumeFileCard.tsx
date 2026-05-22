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
  const profile = parsedResume?.extractedProfile;
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
            <strong>{parsedResume.chunks.length}</strong>
            <span>检索片段</span>
          </div>
        </div>
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
