import type { ParsedResume, ResumeChunk, ResumeRetrievalResult } from "../types/resume";
import { validateResumeFile } from "../utils/fileValidation";
import { mockParseResumeFile } from "../utils/mockResumeParser";
import { mockRetrieveRelevantResumeChunks } from "../utils/mockRagRetriever";

interface UploadResponse {
  resumeFile?: ParsedResume["file"];
  parsedResume?: ParsedResume;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function parseApiError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || "文件解析失败，请检查文件是否损坏或加密";
  } catch {
    return "文件解析失败，请检查文件是否损坏或加密";
  }
}

export async function parseResumeFile(file: File): Promise<ParsedResume> {
  const validationError = validateResumeFile(file);
  if (validationError) throw new Error(validationError);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/api/resumes/upload", {
      method: "POST",
      body: formData,
    });

    if (response.status === 404 || response.status >= 500) {
      return mockParseResumeFile(file);
    }
    if (!response.ok) {
      throw new Error(await parseApiError(response));
    }

    const payload = (await response.json()) as UploadResponse;
    if (!payload.parsedResume) {
      throw new Error("解析服务返回结果格式异常");
    }
    return payload.parsedResume;
  } catch (error) {
    if (error instanceof TypeError) {
      return mockParseResumeFile(file);
    }
    throw error;
  }
}

export async function buildResumeIndex(parsedResume: ParsedResume): Promise<ResumeChunk[]> {
  await sleep(420);
  if (!parsedResume.chunks.length) {
    throw new Error("简历解析成功但没有生成可检索片段");
  }
  return parsedResume.chunks.map((chunk) => ({
    ...chunk,
    keywords: chunk.keywords ?? [],
  }));
}

export async function retrieveRelevantResumeChunks(
  jdText: string,
  chunks: ResumeChunk[],
  options: { topK?: number } = {},
): Promise<ResumeRetrievalResult> {
  await sleep(360);
  const resumeFileId = chunks[0]?.resumeFileId;
  if (resumeFileId) {
    try {
      const response = await fetch("/api/resumes/retrieve", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jdText,
          resumeFileId,
          topK: options.topK ?? 8,
        }),
      });
      if (response.ok) {
        return (await response.json()) as ResumeRetrievalResult;
      }
    } catch {
      // Local mock retrieval keeps the personal workbench usable without the API.
    }
  }
  return mockRetrieveRelevantResumeChunks(jdText, chunks, options);
}
