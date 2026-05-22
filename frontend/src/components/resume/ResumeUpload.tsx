import type { DragEvent } from "react";
import { useRef, useState } from "react";
import type { ParsedResume, ResumeFileStatus, UploadedResumeFile } from "../../types/resume";
import { RESUME_MAX_FILE_SIZE, formatFileSize } from "../../utils/fileValidation";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ResumeFileCard } from "./ResumeFileCard";
import { ResumeParseStatus } from "./ResumeParseStatus";

interface ResumeUploadProps {
  resumeFile: UploadedResumeFile | null;
  parsedResume: ParsedResume | null;
  status: ResumeFileStatus;
  error: string;
  disabled?: boolean;
  onSelectFile: (file: File) => void;
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
  onRetry,
  onRemove,
}: ResumeUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  function chooseFile() {
    inputRef.current?.click();
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files.item(0);
    if (file) onSelectFile(file);
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
        <Button type="button" variant="primary" onClick={chooseFile} disabled={disabled}>
          {resumeFile ? "重新上传" : "选择文件"}
        </Button>
      </div>

      <p className="privacy-note">
        你的简历可能包含手机号、邮箱、教育经历等敏感信息。当前版本优先在本地解析和保存数据，不会主动上传到云端；若后端服务可用，则仅用于本次解析和岗位匹配分析。
      </p>

      {resumeFile && (
        <ResumeFileCard file={resumeFile} parsedResume={parsedResume} error={error} onRetry={onRetry} onRemove={onRemove} />
      )}
    </Card>
  );
}
