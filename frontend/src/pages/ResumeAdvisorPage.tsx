import { FormEvent, useEffect, useMemo, useState } from "react";
import { fetchConfigs } from "../services/configService";
import { deleteProjectKnowledgeDocument, fetchProjectKnowledgeDocuments, uploadProjectKnowledgeDocument } from "../services/projectKnowledgeService";
import type { ChatModelConfig } from "../types/modelConfig";
import type { ProjectKnowledgeDocument } from "../types/projectKnowledge";

type ResumeFile = { id: string; name: string; type?: string; size?: number };
type Block = { id: string; text: string; section: string; location?: Record<string, unknown> };
type Diff = { targetBlockId: string; originalText: string; replacementText: string; reason: string; priority?: string };
type Snapshot = { sessionId: string; status: string; messages: Array<{ role: string; content: string }>; resumeBlocks: Block[]; diffs: Diff[]; evidence: Array<{ text: string; score?: number }>; hr: { matched?: boolean; strengths?: Array<{ targetBlockId?: string; reason: string }>; risks?: Array<{ targetBlockId?: string; reason: string }> } };

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "include", headers: { "Content-Type": "application/json", ...(init?.headers || {}) }, ...init });
  if (!response.ok) throw new Error((await response.json().catch(() => ({})) as { detail?: string }).detail || "请求失败");
  return response.json() as Promise<T>;
}

export function ResumeAdvisorPage() {
  const [resumes, setResumes] = useState<ResumeFile[]>([]);
  const [projects, setProjects] = useState<ProjectKnowledgeDocument[]>([]);
  const [models, setModels] = useState<ChatModelConfig[]>([]);
  const [resumeId, setResumeId] = useState("");
  const [jd, setJd] = useState("");
  const [modelId, setModelId] = useState("");
  const [selectedProjects, setSelectedProjects] = useState<number[]>([]);
  const [uploadOpen, setUploadOpen] = useState(true);
  const [projectOpen, setProjectOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [message, setMessage] = useState("");
  const [activeBlock, setActiveBlock] = useState("");
  const [previewFile, setPreviewFile] = useState<{ type?: string; b64?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    const [resumeData, projectData, configData] = await Promise.all([
      json<{ resumes: ResumeFile[] }>("/api/resumes"),
      fetchProjectKnowledgeDocuments(),
      fetchConfigs(),
    ]);
    setResumes(resumeData.resumes || []);
    setResumeId((value) => value || resumeData.resumes?.[0]?.id || "");
    setProjects(projectData);
    setModels(configData.chatConfigs.filter((item) => item.enabled));
    setModelId((value) => value || configData.active.chatConfigId || configData.chatConfigs.find((item) => item.enabled)?.id || "");
  };

  useEffect(() => { void refresh().catch((reason) => setError(reason.message)); }, []);
  useEffect(() => {
    if (!resumeId) { setPreviewFile(null); return; }
    void json<{ parsedResume?: { file?: { type?: string; b64_content?: string } } }>(`/api/resumes/${encodeURIComponent(resumeId)}`)
      .then((result) => setPreviewFile(result.parsedResume?.file ? { type: result.parsedResume.file.type, b64: result.parsedResume.file.b64_content } : null))
      .catch((reason) => setError(reason.message));
  }, [resumeId]);
  useEffect(() => {
    if (!snapshot || !["PENDING", "RUNNING"].includes(snapshot.status)) return;
    const timer = window.setInterval(() => void json<Snapshot>(`/api/resume-optimization/sessions/${snapshot.sessionId}`).then(setSnapshot).catch((reason) => setError(reason.message)), 1500);
    return () => window.clearInterval(timer);
  }, [snapshot?.sessionId, snapshot?.status]);

  const uploadResume = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setError("");
    try {
      for (const file of Array.from(files)) {
        const form = new FormData(); form.append("file", file);
        const response = await fetch("/api/resumes/upload", { method: "POST", credentials: "include", body: form });
        if (!response.ok) throw new Error("简历上传失败");
      }
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "简历上传失败"); } finally { setBusy(false); }
  };

  const uploadProjects = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setError("");
    try { for (const file of Array.from(files)) await uploadProjectKnowledgeDocument(file); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "项目资料上传失败"); } finally { setBusy(false); }
  };

  const deleteResume = async (id: string) => {
    try {
      const response = await fetch(`/api/resumes/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "include" });
      if (!response.ok) throw new Error("删除简历失败");
      if (resumeId === id) setResumeId("");
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "删除简历失败"); }
  };

  const start = async () => {
    if (!resumeId || !jd.trim()) { setError("请选择简历并输入 JD"); return; }
    setBusy(true); setError("");
    try {
      const result = await json<{ snapshot: Snapshot }>("/api/resume-optimization/sessions", { method: "POST", body: JSON.stringify({ resumeId, jdText: jd, modelConfigId: modelId || null, projectScope: selectedProjects.length ? "selected" : "none", projectDocumentIds: selectedProjects }) });
      setSnapshot(result.snapshot);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "分析失败"); } finally { setBusy(false); }
  };

  const send = async (event: FormEvent) => {
    event.preventDefault(); if (!snapshot || !message.trim()) return;
    setBusy(true);
    try { const result = await json<{ snapshot: Snapshot }>(`/api/resume-optimization/sessions/${snapshot.sessionId}/messages`, { method: "POST", body: JSON.stringify({ message }) }); setSnapshot(result.snapshot); setMessage(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "发送失败"); } finally { setBusy(false); }
  };

  const focus = (blockId: string) => { setActiveBlock(blockId); document.getElementById(`resume-block-${blockId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); };
  const copy = async (value: string) => { await navigator.clipboard.writeText(value); };
  const highlights = useMemo(() => new Set(snapshot?.diffs.map((item) => item.targetBlockId) || []), [snapshot]);

  return <main style={{ display: "grid", gridTemplateColumns: "minmax(260px, .8fr) minmax(420px, 1.35fr) minmax(320px, 1fr)", gap: 12, padding: 16, height: "calc(100vh - 32px)", boxSizing: "border-box", background: "#f5f7fb" }}>
    <aside style={{ overflow: "auto", display: "grid", gap: 12, alignContent: "start" }}>
      <section style={{ background: "white", padding: 14, border: "1px solid #dce3ee" }}><button onClick={() => setUploadOpen(!uploadOpen)}>{uploadOpen ? "收起" : "展开"}简历上传</button>{uploadOpen && <><input multiple accept=".pdf,.docx,.txt,.md" type="file" onChange={(e) => void uploadResume(e.target.files)} disabled={busy}/><select value={resumeId} onChange={(e) => setResumeId(e.target.value)}><option value="">选择简历</option>{resumes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{resumes.map((item) => <div key={item.id}><span>{item.name}</span><button onClick={() => void deleteResume(item.id)} disabled={busy}>删除</button></div>)}</>}</section>
      <section style={{ background: "white", padding: 14, border: "1px solid #dce3ee" }}><button onClick={() => setProjectOpen(!projectOpen)}>{projectOpen ? "收起" : "展开"}项目经历资料</button>{projectOpen && <><input multiple accept=".pdf,.docx,.txt,.md" type="file" onChange={(e) => void uploadProjects(e.target.files)} disabled={busy}/>{projects.map((item) => <div key={item.id}><label><input type="checkbox" checked={selectedProjects.includes(item.id)} onChange={() => setSelectedProjects((ids) => ids.includes(item.id) ? ids.filter((id) => id !== item.id) : [...ids, item.id])}/>{item.file_name || item.title}</label><button onClick={() => void deleteProjectKnowledgeDocument(item.id).then(refresh)}>删除</button></div>)}</>}</section>
      <section style={{ background: "white", padding: 14, border: "1px solid #dce3ee" }}><label>模型配置<select value={modelId} onChange={(e) => setModelId(e.target.value)}><option value="">系统默认</option>{models.map((item) => <option key={item.id} value={item.id}>{item.name} / {item.modelId}</option>)}</select></label><textarea value={jd} onChange={(e) => setJd(e.target.value)} placeholder="粘贴职位描述" rows={10}/><button onClick={() => void start()} disabled={busy}>开始定向优化</button></section>
    </aside>
    <section style={{ background: "white", border: "1px solid #dce3ee", display: "grid", gridTemplateRows: "1fr auto", minHeight: 0 }}><div style={{ overflow: "auto", padding: 18 }}><h2>与简历优化 Agent 对话</h2>{snapshot && <small>编排状态：{snapshot.status}</small>}{!snapshot && <p>上传简历、输入 JD 后，Agent 会在这里解释匹配情况和修改建议。</p>}{snapshot?.messages.map((item, index) => <p key={index} style={{ whiteSpace: "pre-wrap", padding: 10, background: item.role === "user" ? "#e8f1ff" : "#f7f8fa" }}><b>{item.role === "user" ? "你" : "Agent"}：</b>{item.content}</p>)}{snapshot?.diffs.map((item, index) => <article key={index} style={{ borderLeft: "4px solid #d97706", padding: 10, marginTop: 8 }}><button onClick={() => focus(item.targetBlockId)}>定位修改位置</button><button onClick={() => void copy(item.replacementText)}>复制修改结果</button><p><del>{item.originalText}</del></p><p><b>{item.replacementText}</b></p><small>{item.reason}</small></article>)}{snapshot?.hr.matched && <div><h3>匹配亮点</h3>{(snapshot.hr.strengths || []).map((item, index) => <button key={index} onClick={() => item.targetBlockId && focus(item.targetBlockId)}>{item.reason}</button>)}</div>}</div><form onSubmit={(e) => void send(e)} style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid #dce3ee" }}><input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="继续追问、补充事实或确认完成" disabled={!snapshot || busy || snapshot.status !== "COMPLETED"}/><button disabled={!snapshot || busy || snapshot.status !== "COMPLETED"}>发送</button></form></section>
    <aside style={{ background: "white", border: "1px solid #dce3ee", overflow: "auto", padding: 14 }}><h2>简历预览</h2>{previewFile?.type === "application/pdf" && previewFile.b64 && <iframe title="原始 PDF 简历" src={`data:application/pdf;base64,${previewFile.b64}`} style={{ border: 0, width: "100%", height: 340 }} />}{snapshot?.resumeBlocks.map((block) => <article id={`resume-block-${block.id}`} key={block.id} style={{ padding: 10, marginBottom: 8, background: activeBlock === block.id ? "#fff3cd" : highlights.has(block.id) ? "#fff7e6" : "#fff", border: "1px solid #e1e6ef" }}><small>{block.section}</small><p>{block.text}</p></article>)}<h3>检索证据</h3>{snapshot?.evidence.map((item, index) => <p key={index}>{item.text}</p>)}</aside>
    {error && <div style={{ position: "fixed", bottom: 16, left: "50%", color: "#991b1b", background: "#fee2e2", padding: 10 }}>{error}</div>}
  </main>;
}
