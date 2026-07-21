import type { ProjectKnowledgeDocument } from "../types/projectKnowledge";

async function readApiError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    return data.detail || "项目资料请求失败";
  } catch {
    return "项目资料请求失败";
  }
}

export async function fetchProjectKnowledgeDocuments(): Promise<ProjectKnowledgeDocument[]> {
  const response = await fetch("/api/materials?source_type=project", { credentials: "include" });
  if (!response.ok) throw new Error(await readApiError(response));
  const payload = (await response.json()) as { documents?: ProjectKnowledgeDocument[] };
  const names = new Set<string>();
  return (payload.documents || []).filter((document) => {
    if (document.source_type !== "project") return false;
    const name = (document.file_name || document.title).trim().replace(/\s+/g, " ").toLocaleLowerCase();
    if (names.has(name)) return false;
    names.add(name);
    return true;
  });
}

export async function uploadProjectKnowledgeDocument(file: File, title = ""): Promise<ProjectKnowledgeDocument> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", title);
  formData.append("source_type", "project");
  const response = await fetch("/api/materials", {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!response.ok) throw new Error(await readApiError(response));
  const payload = (await response.json()) as { document?: ProjectKnowledgeDocument };
  if (!payload.document) throw new Error("项目资料上传成功但未返回资料信息");
  if (payload.document.status === "FAILED") {
    throw new Error(payload.document.error_message || "项目资料解析失败");
  }
  return payload.document;
}

export async function deleteProjectKnowledgeDocument(documentId: number): Promise<void> {
  const response = await fetch(`/api/materials/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok) throw new Error(await readApiError(response));
}
