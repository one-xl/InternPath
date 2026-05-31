import { useState } from "react";
import { buildResumeIndex, parseResumeFile, vectorizeResume, fetchSavedResume } from "../services/resumeService";
import type { ParsedResume, ResumeChunk, ResumeFileStatus, UploadedResumeFile } from "../types/resume";
import { validateResumeFile } from "../utils/fileValidation";
import { safeUUID } from "../utils/uuid";

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
        id: safeUUID(),
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
      id: safeUUID(),
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

      const shouldVectorize = window.confirm(
        "是否将该简历转换成向量并存储？\n\n（“确定”：立即进行简历向量化，下次使用可以直接选择；“取消”：暂不计算，仅在点击开始分析时才进行即时向量化）"
      );

      setStatus("indexing");
      setResumeFile((current) => (current ? { ...current, status: "indexing" } : current));

      let finalParsed = parsed;
      if (shouldVectorize) {
        try {
          await vectorizeResume(parsed.file.id);
          finalParsed = await fetchSavedResume(parsed.file.id);
          setParsedResume(finalParsed);
        } catch (vErr) {
          console.error("简历向量化持久化失败:", vErr);
          alert("简历向量化失败，将降级为分析时即时计算。");
        }
      }

      const indexedChunks = await buildResumeIndex(finalParsed);
      setChunks(indexedChunks);
      setResumeFile((current) => (current ? { ...current, status: "indexed" } : null));
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

  async function selectSavedResume(parsed: ParsedResume) {
    try {
      setStatus("indexing");
      setSourceFile(null);
      setParsedResume(parsed);
      setResumeFile({ ...parsed.file, status: "indexing" });
      
      const indexedChunks = await buildResumeIndex(parsed);
      setChunks(indexedChunks);
      setResumeFile({ ...parsed.file, status: "indexed" });
      setStatus("indexed");
      setError("");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "文件索引生成失败";
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
    selectSavedResume,
    removeFile,
    retry,
    reset: removeFile,
    restoreResumeData,
  };
}
