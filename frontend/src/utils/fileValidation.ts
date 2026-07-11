const SUPPORTED_MIME_TYPES = new Set([
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
]);

const SUPPORTED_EXTENSIONS = new Set([".pdf", ".doc", ".docx", ".txt"]);
export const RESUME_MAX_FILE_SIZE = 10 * 1024 * 1024;

export function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function getFileExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf(".");
  return dotIndex >= 0 ? fileName.slice(dotIndex).toLowerCase() : "";
}

export function validateResumeFile(file: File): string | null {
  if (file.size === 0) return "文件为空，请重新选择";
  if (file.size > RESUME_MAX_FILE_SIZE) return "文件大小不能超过 10MB";

  const extension = getFileExtension(file.name);
  const mimeAllowed = SUPPORTED_MIME_TYPES.has(file.type);
  const extensionAllowed = SUPPORTED_EXTENSIONS.has(extension);
  if (!mimeAllowed && !extensionAllowed) return "仅支持 PDF、DOC、DOCX、TXT 格式";

  return null;
}
