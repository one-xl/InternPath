const state = {
  sessions: [],
  activeId: null,
  resumes: [],
  projects: [],
  configs: [],
  selectedResumeId: "",
  selectedProjectIds: new Set(),
  modelConfigId: "",
  jdText: "",
  focusedBlockId: "",
  pollTimer: null,
  lastFocusedElement: null,
};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: "include", ...options });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "请求失败，请稍后重试。");
  }
  return response.json();
}

function activeSession() {
  return state.sessions.find((session) => session.id === state.activeId) || null;
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 1800);
}

function setStatus(status) {
  const dot = $("statusDot");
  dot.className = "status-dot";
  const labels = { RUNNING: "正在编排", PENDING: "等待执行", COMPLETED: "分析完成", FAILED: "运行失败" };
  if (["RUNNING", "PENDING"].includes(status)) dot.classList.add("running");
  if (status === "COMPLETED") dot.classList.add("ready");
  $("statusText").textContent = labels[status] || "等待材料";
}

function openSetup() {
  state.lastFocusedElement = document.activeElement;
  $("setupModal").classList.add("open");
  $("setupModal").setAttribute("aria-hidden", "false");
  renderSetup();
  window.setTimeout(() => $("resumeUpload").focus(), 0);
}

function closeSetup() {
  $("setupModal").classList.remove("open");
  $("setupModal").setAttribute("aria-hidden", "true");
  state.lastFocusedElement?.focus?.();
}

function renderSetup() {
  $("jdInput").value = state.jdText;
  $("modelSelect").innerHTML = '<option value="">系统默认</option>' + state.configs.map((config) => `<option value="${escapeHtml(config.id)}">${escapeHtml(config.name || config.modelId)} / ${escapeHtml(config.modelId || "")}</option>`).join("");
  $("modelSelect").value = state.modelConfigId;
  renderResumeList();
  renderProjectList();
}

function renderResumeList() {
  const holder = $("resumeList");
  if (!state.resumes.length) { holder.innerHTML = '<p class="empty-state">还没有简历文件。</p>'; return; }
  holder.innerHTML = state.resumes.map((resume) => `<div class="file-row"><label><input type="radio" name="resume" value="${escapeHtml(resume.id)}" ${resume.id === state.selectedResumeId ? "checked" : ""}> ${escapeHtml(resume.name || resume.file_name || "未命名简历")}</label><button class="delete-file" data-delete-resume="${escapeHtml(resume.id)}" aria-label="删除简历" title="删除简历">&times;</button></div>`).join("");
}

function renderProjectList() {
  const holder = $("projectList");
  if (!state.projects.length) { holder.innerHTML = '<p class="empty-state">项目资料会作为 Hybrid RAG 的候选证据。</p>'; return; }
  const allSelected = state.projects.every((p) => state.selectedProjectIds.has(Number(p.id)));
  const btnLabel = allSelected ? "取消全选" : "全选";
  holder.innerHTML = `<div class="file-row" style="margin-bottom:4px"><button class="small-btn" id="toggleAllProjects">${btnLabel}</button><span style="color:var(--muted);font-size:11px">已选 ${state.selectedProjectIds.size} / ${state.projects.length}</span></div>` +
    state.projects.map((project) => `<div class="file-row"><label><input type="checkbox" data-project-id="${project.id}" ${state.selectedProjectIds.has(Number(project.id)) ? "checked" : ""}> ${escapeHtml(project.file_name || project.title || "未命名资料")}</label><button class="delete-file" data-delete-project="${project.id}" aria-label="删除项目资料" title="删除项目资料">&times;</button></div>`).join("");
}

function renderTabs() {
  const holder = $("sessionTabs");
  if (!state.sessions.length) { holder.innerHTML = '<button class="tab-btn active" type="button">新建优化会话</button>'; return; }
  holder.innerHTML = state.sessions.map((session, index) => `<button class="tab-btn ${session.id === state.activeId ? "active" : ""}" data-session-id="${escapeHtml(session.id)}" title="${escapeHtml(session.title)}">${index + 1}. ${escapeHtml(session.title)}</button>`).join("");
}

function renderMessages() {
  const holder = $("messagesList");
  const session = activeSession();
  if (!session) {
    holder.innerHTML = `<div class="welcome-card"><h2>从一场对话开始优化</h2><p>上传简历，添加 JD 和项目经历资料。主控智能体会串联 JD 分析师、简历修改师与 HR 分析师，并把检索到的证据带入对话。</p><div class="quick-prompts"><button class="quick-btn" id="welcomeStart">配置材料并开始</button><button class="quick-btn" id="welcomeRag">了解 Hybrid RAG</button></div></div>`;
    $("welcomeStart").addEventListener("click", openSetup);
    $("welcomeRag").addEventListener("click", () => showToast("项目资料会通过关键词/BM25、向量检索和重排作为证据输入。"));
    return;
  }
  const messages = session.snapshot?.messages || [];
  holder.innerHTML = messages.map((message) => `<article class="message ${message.role === "user" ? "user" : "assistant"}"><span class="message-label">${message.role === "user" ? "你" : "简历优化 Agent"}</span><div class="message-body">${escapeHtml(message.content)}</div></article>`).join("") || '<p class="empty-state">正在准备对话。</p>';
  holder.scrollTop = holder.scrollHeight;
}

function renderRuntime() {
  const session = activeSession();
  const snapshot = session?.snapshot;
  const status = snapshot?.status || "";
  setStatus(status);
  $("currentSessionTag").textContent = snapshot ? status : "未开始";
  const config = state.configs.find((item) => item.id === state.modelConfigId);
  $("activeModelTag").textContent = config?.modelId || "系统默认";
  $("modelModeDesc").textContent = config ? `${config.name || config.modelId} 已用于本次会话。` : "将使用系统默认的可用模型配置。";

  const events = snapshot?.events || [];
  $("traceList").innerHTML = events.length ? events.map((event) => `<div class="trace-item"><div class="trace-name">${escapeHtml(agentName(event.agent))}</div><div class="trace-state">${escapeHtml(event.status || "已完成")}</div></div>`).join("") : '<p class="empty-state">开始分析后显示主控、JD、修改与 HR 节点状态。</p>';

  const evidence = snapshot?.evidence || [];
  $("evidenceCount").textContent = String(evidence.length);
  $("evidenceList").innerHTML = evidence.length ? evidence.slice(0, 8).map((item) => `<div class="evidence-item"><div>${escapeHtml(item.text || item.content || "检索片段")}</div><div class="evidence-meta">${escapeHtml(item.metadata?.sourceType || item.sourceType || "证据")}${item.score != null ? ` · ${Number(item.score).toFixed(2)}` : ""}</div></div>`).join("") : '<p class="empty-state">暂无检索证据</p>';

  const diffs = snapshot?.diffs || [];
  $("diffList").innerHTML = diffs.length ? diffs.map((diff, index) => `<article class="diff-item"><strong>建议 ${index + 1}</strong><div class="diff-reason">${escapeHtml(diff.reason || "基于 JD 与证据的建议")}</div><div class="diff-before">${escapeHtml(diff.originalText || "")}</div><div class="diff-after">${escapeHtml(diff.replacementText || "")}</div><div class="small-actions"><button data-focus-block="${escapeHtml(diff.targetBlockId || "")}">定位</button><button data-copy="${encodeURIComponent(diff.replacementText || "")}">复制</button></div></article>`).join("") : '<p class="empty-state">完成分析后在这里查看可复制、可定位的修改建议。</p>';

  const blocks = snapshot?.resumeBlocks || [];
  const resume = state.resumes.find((item) => item.id === state.selectedResumeId);
  const pdf = resume?.file?.type === "application/pdf" && resume.file?.b64_content ? `<iframe class="preview-pdf" title="原始 PDF 简历" src="data:application/pdf;base64,${resume.file.b64_content}"></iframe>` : "";
  const blockHtml = blocks.length ? blocks.map((block) => `<article id="resume-block-${escapeHtml(block.id)}" class="preview-block ${block.id === state.focusedBlockId ? "focused" : ""}"><div class="preview-section">${escapeHtml(block.section || "简历内容")}</div><p class="preview-text">${escapeHtml(block.text)}</p></article>`).join("") : '<p class="empty-state">分析开始后显示可定位的简历结构化文本。</p>';
  $("previewContent").innerHTML = pdf + blockHtml;
}

function agentName(name) {
  return ({ orchestrator: "主控智能体", jd_analyst: "JD 分析师", hybrid_rag: "Hybrid RAG", resume_editor: "简历修改师", hr_analyst: "HR 分析师" })[name] || name || "运行节点";
}

function renderAll() { renderTabs(); renderMessages(); renderRuntime(); }

async function loadResources() {
  const [resumeData, materialData, configData] = await Promise.all([api("/api/resumes"), api("/api/materials?source_type=project"), api("/api/configs")]);
  state.resumes = resumeData.resumes || [];
  state.projects = (materialData.documents || []).filter((item) => item.source_type === "project");
  state.configs = (configData.configs || []).filter((item) => item.type === "chat" && item.enabled !== false);
  if (!state.selectedResumeId && state.resumes[0]) state.selectedResumeId = state.resumes[0].id;
  if (!state.modelConfigId) state.modelConfigId = configData.active?.chatConfigId || state.configs[0]?.id || "";
  renderAll();
}

async function uploadFiles(files, kind) {
  for (const file of Array.from(files || [])) {
    const form = new FormData();
    form.append("file", file);
    if (kind === "project") { form.append("source_type", "project"); form.append("title", file.name); }
    await api(kind === "project" ? "/api/materials" : "/api/resumes/upload", { method: "POST", body: form });
  }
  await loadResources();
  renderSetup();
  showToast("文件已上传");
}

async function startAnalysis() {
  state.jdText = $("jdInput").value.trim();
  state.modelConfigId = $("modelSelect").value;
  if (!state.selectedResumeId || !state.jdText) { showToast("请先选择简历并填写 JD"); return; }
  $("startAnalysisBtn").disabled = true;
  try {
    const payload = { resumeId: state.selectedResumeId, jdText: state.jdText, modelConfigId: state.modelConfigId || null, projectScope: state.selectedProjectIds.size ? "selected" : "none", projectDocumentIds: [...state.selectedProjectIds] };
    const result = await api("/api/resume-optimization/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const title = `${state.resumes.find((item) => item.id === state.selectedResumeId)?.name || "简历"} · ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    state.sessions.push({ id: result.sessionId, title, snapshot: result.snapshot });
    state.activeId = result.sessionId;
    closeSetup(); renderAll(); startPolling();
  } catch (error) { showToast(error.message); } finally { $("startAnalysisBtn").disabled = false; }
}

async function refreshSnapshot() {
  const session = activeSession();
  if (!session) return;
  try {
    session.snapshot = await api(`/api/resume-optimization/sessions/${encodeURIComponent(session.id)}`);
    renderAll();
    if (!["PENDING", "RUNNING"].includes(session.snapshot.status)) stopPolling();
  } catch (error) { stopPolling(); showToast(error.message); }
}

function startPolling() { stopPolling(); state.pollTimer = window.setInterval(refreshSnapshot, 1400); }
function stopPolling() { if (state.pollTimer) window.clearInterval(state.pollTimer); state.pollTimer = null; }

async function sendMessage(event) {
  event.preventDefault();
  const session = activeSession();
  const message = $("userInput").value.trim();
  if (!session || !message) { if (!session) openSetup(); return; }
  $("sendBtn").disabled = true;
  try {
    const result = await api(`/api/resume-optimization/sessions/${encodeURIComponent(session.id)}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
    session.snapshot = result.snapshot; $("userInput").value = ""; renderAll();
  } catch (error) { showToast(error.message); } finally { $("sendBtn").disabled = false; }
}

function focusBlock(blockId) {
  if (!blockId) return;
  state.focusedBlockId = blockId;
  document.querySelector('[data-panel="previewPanel"]').click();
  renderRuntime();
  window.setTimeout(() => $("resume-block-" + blockId)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
}

function wireEvents() {
  $("openSetupBtn").addEventListener("click", openSetup); $("newSessionBtn").addEventListener("click", openSetup);
  $("closeSetupBtn").addEventListener("click", closeSetup); $("cancelSetupBtn").addEventListener("click", closeSetup); $("startAnalysisBtn").addEventListener("click", startAnalysis);
  $("resumeUpload").addEventListener("change", (event) => uploadFiles(event.target.files, "resume").catch((error) => showToast(error.message)));
  $("projectUpload").addEventListener("change", (event) => uploadFiles(event.target.files, "project").catch((error) => showToast(error.message)));
  $("resumeList").addEventListener("change", (event) => { if (event.target.name === "resume") { state.selectedResumeId = event.target.value; renderSetup(); renderRuntime(); } });
  $("projectList").addEventListener("change", (event) => { if (event.target.dataset.projectId) { const id = Number(event.target.dataset.projectId); event.target.checked ? state.selectedProjectIds.add(id) : state.selectedProjectIds.delete(id); } });
  $("resumeList").addEventListener("click", async (event) => { const id = event.target.dataset.deleteResume; if (!id) return; await api(`/api/resumes/${encodeURIComponent(id)}`, { method: "DELETE" }); if (state.selectedResumeId === id) state.selectedResumeId = ""; await loadResources(); renderSetup(); });
  $("projectList").addEventListener("click", async (event) => { if (event.target.id === "toggleAllProjects") { const allSelected = state.projects.every((p) => state.selectedProjectIds.has(Number(p.id))); if (allSelected) { state.selectedProjectIds.clear(); } else { state.projects.forEach((p) => state.selectedProjectIds.add(Number(p.id))); } renderProjectList(); return; } const id = event.target.dataset.deleteProject; if (!id) return; await api(`/api/materials/${encodeURIComponent(id)}`, { method: "DELETE" }); state.selectedProjectIds.delete(Number(id)); await loadResources(); renderSetup(); });
  $("chatForm").addEventListener("submit", sendMessage);
  $("sessionTabs").addEventListener("click", (event) => { const id = event.target.dataset.sessionId; if (id) { state.activeId = id; renderAll(); if (["PENDING", "RUNNING"].includes(activeSession()?.snapshot?.status)) startPolling(); } });
  $("diffList").addEventListener("click", async (event) => { const blockId = event.target.dataset.focusBlock; const copy = event.target.dataset.copy; if (blockId) focusBlock(blockId); if (copy !== undefined) { await navigator.clipboard.writeText(decodeURIComponent(copy)); showToast("修改结果已复制"); } });
  document.querySelectorAll(".drawer-tab").forEach((tab) => tab.addEventListener("click", () => { document.querySelectorAll(".drawer-tab, .drawer-panel").forEach((item) => item.classList.remove("active")); tab.classList.add("active"); $(tab.dataset.panel).classList.add("active"); }));
  $("toggleDrawerBtn").addEventListener("click", () => $("runtimeDrawer").classList.add("open")); $("closeDrawerBtn").addEventListener("click", () => $("runtimeDrawer").classList.remove("open"));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeSetup(); $("runtimeDrawer").classList.remove("open"); } });
}

document.addEventListener("DOMContentLoaded", async () => { wireEvents(); try { await loadResources(); } catch (error) { showToast(error.message); } });
