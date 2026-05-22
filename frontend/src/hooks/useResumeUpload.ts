import { useState } from "react";
import { buildResumeIndex, parseResumeFile } from "../services/resumeService";
import type { ParsedResume, ResumeChunk, ResumeFileStatus, UploadedResumeFile } from "../types/resume";
import { validateResumeFile } from "../utils/fileValidation";

export function useResumeUpload() {
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [resumeFile, setResumeFile] = useState<UploadedResumeFile | null>(null);
  const [parsedResume, setParsedResume] = useState<ParsedResume | null>(null);
  const [chunks, setChunks] = useState<ResumeChunk[]>([]);
  const [status, setStatus] = useState<ResumeFileStatus>("idle");
  const [error, setError] = useState("");

  async function selectFile(file: File) {
    const validationError = validateResumeFile(file);
    if (validationError) {
      setError(validationError);
      setStatus("failed");
      setSourceFile(file);
      setResumeFile({
        id: crypto.randomUUID(),
        name: file.name,
        size: file.size,
        type: file.type,
        uploadedAt: new Date().toISOString(),
        status: "failed",
        errorMessage: validationError,
      });
      return;
    }

    setSourceFile(file);
    setParsedResume(null);
    setChunks([]);
    setError("");
    setStatus("selected");
    setResumeFile({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      type: file.type,
      uploadedAt: new Date().toISOString(),
      status: "selected",
    });

    try {
      setStatus("uploading");
      setResumeFile((current) => (current ? { ...current, status: "uploading" } : current));
      setStatus("parsing");
      setResumeFile((current) => (current ? { ...current, status: "parsing" } : current));
      const parsed = await parseResumeFile(file);
      setParsedResume(parsed);
      setResumeFile({ ...parsed.file, status: "parsed" });
      setStatus("parsed");

      setStatus("indexing");
      setResumeFile((current) => (current ? { ...current, status: "indexing" } : current));
      const indexedChunks = await buildResumeIndex(parsed);
      setChunks(indexedChunks);
      setResumeFile({ ...parsed.file, status: "indexed" });
      setStatus("indexed");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "文件解析失败，请检查文件是否损坏或加密";
      setError(message);
      setStatus("failed");
      setResumeFile((current) =>
        current
          ? {
              ...current,
              status: "failed",
              errorMessage: message,
            }
          : current,
      );
    }
  }

  function removeFile() {
    setSourceFile(null);
    setResumeFile(null);
    setParsedResume(null);
    setChunks([]);
    setStatus("idle");
    setError("");
  }

  async function retry() {
    if (sourceFile) {
      await selectFile(sourceFile);
    }
  }

  function restoreResumeData(file: UploadedResumeFile | null, parsed: ParsedResume | null, chunksData: ResumeChunk[]) {
    setSourceFile(null);
    setResumeFile(file);
    setParsedResume(parsed);
    setChunks(chunksData || []);
    setStatus(file ? (file.status as ResumeFileStatus) : "idle");
    setError(file?.errorMessage || "");
  }

  return {
    sourceFile,
    resumeFile,
    parsedResume,
    chunks,
    status,
    error,
    isReady: status === "indexed" && Boolean(parsedResume) && chunks.length > 0,
    selectFile,
    removeFile,
    retry,
    reset: removeFile,
    restoreResumeData,
  };
}
