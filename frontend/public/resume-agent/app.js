/**
 * Minimal Agent Runtime Web App JS 核心逻辑
 * 实现多 Session 选项卡切换、右键弹出菜单删除窗口、与后端 Agent REST API 通信、
 * Trace 动态渲染、大模型 API 动态配置及历史 Session 磁盘落盘与恢复。
 */

let activeSessionId = "window_1";
let contextMenuSessionTarget = null;
const sessionMessagesMap = {};

// 页面加载完成后初始化
document.addEventListener("DOMContentLoaded", async () => {
    initTabs();
    initContextMenu();
    initChatForm();
    initConfigModal();
    fetchCurrentConfig();
    await loadHistorySessions();
    refreshTodos(activeSessionId);
});

// 拉取已持久化落盘的历史 Session 列表并动态构建选项卡
async function loadHistorySessions() {
    try {
        const res = await fetch("/api/sessions");
        if (res.ok) {
            const data = await res.json();
            const sessions = data.sessions || [{ session_id: "window_1", title: "窗口 1" }];
            const sessionTabs = document.getElementById("sessionTabs");
            sessionTabs.innerHTML = "";

            sessions.forEach((sItem, idx) => {
                const sId = typeof sItem === "string" ? sItem : sItem.session_id;
                const title = typeof sItem === "string" ? `窗口 ${sId.replace('window_', '')}` : (sItem.title || sId);

                sessionMessagesMap[sId] = [];
                const tab = document.createElement("button");
                tab.className = `tab-btn ${idx === 0 ? "active" : ""}`;
                tab.setAttribute("data-session", sId);
                tab.innerHTML = `<span class="tab-icon">💬</span> <span class="tab-title-text">${escapeHTML(title)}</span>`;
                sessionTabs.appendChild(tab);
            });

            if (sessions.length > 0) {
                const firstId = typeof sessions[0] === "string" ? sessions[0] : sessions[0].session_id;
                activeSessionId = firstId;
                document.getElementById("currentSessionTag").textContent = activeSessionId;
                await loadSessionMessages(activeSessionId);
            }
        }
    } catch (e) {
        console.warn("无法拉取历史 Session 列表:", e);
    }
}

// 从服务器拉取特定 Session 的落盘历史消息并渲染
async function loadSessionMessages(sessionId) {
    try {
        const res = await fetch(`/api/session/messages?session_id=${sessionId}`);
        if (res.ok) {
            const data = await res.json();
            const rawMsgs = data.messages || [];
            
            const formattedList = [];
            let currentGroup = null;

            rawMsgs.forEach(m => {
                if (m.role === "user") {
                    formattedList.push({ role: "user", content: m.content });
                    currentGroup = null;
                } else if (m.role === "assistant") {
                    currentGroup = {
                        final_answer: m.content || "",
                        traces: [{ step: 1, thought: "从磁盘历史持久化恢复的上下文", tool_calls: m.tool_calls || [], tool_results: [] }]
                    };
                    formattedList.push({ role: "agent", response: currentGroup });
                } else if (m.role === "tool") {
                    if (currentGroup && currentGroup.traces.length > 0) {
                        currentGroup.traces[0].tool_results.push({ call_id: m.tool_call_id, name: m.name, output: m.content, is_error: false });
                    }
                }
            });

            sessionMessagesMap[sessionId] = formattedList;
            renderMessagesForSession(sessionId);
        }
    } catch (e) {
        console.warn(`无法拉取 Session [${sessionId}] 历史消息:`, e);
    }
}

// 初始化 Session 选项卡事件（包含左键切换、右键菜单、滚轮横向滑动）
function initTabs() {
    const sessionTabs = document.getElementById("sessionTabs");
    const newSessionBtn = document.getElementById("newSessionBtn");

    // 支持鼠标滚轮自然横向滑动选项卡栏
    sessionTabs.addEventListener("wheel", (e) => {
        if (e.deltaY !== 0) {
            e.preventDefault();
            sessionTabs.scrollLeft += e.deltaY;
        }
    }, { passive: false });

    // 左键切换 Session
    sessionTabs.addEventListener("click", async (e) => {
        const btn = e.target.closest(".tab-btn");
        if (!btn) return;

        const targetSession = btn.getAttribute("data-session");
        await switchSession(targetSession);
    });

    // 右键弹出删除上下文菜单
    sessionTabs.addEventListener("contextmenu", (e) => {
        const btn = e.target.closest(".tab-btn");
        if (!btn) return;

        e.preventDefault();
        const targetSession = btn.getAttribute("data-session");
        contextMenuSessionTarget = targetSession;

        const menu = document.getElementById("tabContextMenu");
        menu.style.left = `${e.clientX}px`;
        menu.style.top = `${e.clientY}px`;
        menu.classList.add("active");
    });

    // 新建 Session 窗口
    newSessionBtn.addEventListener("click", async () => {
        const newSessionId = `window_${Date.now().toString().slice(-4)}`;
        
        sessionMessagesMap[newSessionId] = [];

        const newTab = document.createElement("button");
        newTab.className = "tab-btn";
        newTab.setAttribute("data-session", newSessionId);
        newTab.innerHTML = `<span class="tab-icon">💬</span> <span class="tab-title-text">新对话窗口</span>`;
        sessionTabs.appendChild(newTab);

        await switchSession(newSessionId);
    });
}

// 初始化右键上下文删除菜单事件
function initContextMenu() {
    const menu = document.getElementById("tabContextMenu");
    const deleteBtn = document.getElementById("deleteTabBtn");

    // 全局点击自动关闭右键菜单
    document.addEventListener("click", (e) => {
        if (!menu.contains(e.target)) {
            menu.classList.remove("active");
        }
    });

    // 点击删除特定窗口按钮
    deleteBtn.addEventListener("click", async () => {
        menu.classList.remove("active");
        if (!contextMenuSessionTarget) return;

        const sessionTabs = document.getElementById("sessionTabs");
        const allTabs = Array.from(sessionTabs.querySelectorAll(".tab-btn"));

        if (allTabs.length <= 1) {
            alert("⚠️ 至少需要保留一个 Session 窗口！");
            return;
        }

        const deleteId = contextMenuSessionTarget;

        try {
            // 发起后端 DELETE API 删除内存与磁盘持久化文件
            const res = await fetch(`/api/session?session_id=${deleteId}`, { method: "DELETE" });
            if (res.ok) {
                delete sessionMessagesMap[deleteId];

                // DOM 移除
                const tabToRemove = sessionTabs.querySelector(`.tab-btn[data-session="${deleteId}"]`);
                if (tabToRemove) tabToRemove.remove();

                // 如果删除的是当前激活窗口，自动切换到剩余的窗口
                if (deleteId === activeSessionId) {
                    const remainingTabs = sessionTabs.querySelectorAll(".tab-btn");
                    if (remainingTabs.length > 0) {
                        const nextId = remainingTabs[0].getAttribute("data-session");
                        await switchSession(nextId);
                    }
                }
            } else {
                alert("❌ 删除窗口失败");
            }
        } catch (e) {
            console.error("删除窗口出错:", e);
            alert("❌ 删除出错: " + e.message);
        }
    });
}

// 切换 Session 窗口
async function switchSession(sessionId) {
    activeSessionId = sessionId;

    document.querySelectorAll(".tab-btn").forEach(btn => {
        if (btn.getAttribute("data-session") === sessionId) {
            btn.classList.add("active");
            btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
        } else {
            btn.classList.remove("active");
        }
    });

    document.getElementById("currentSessionTag").textContent = sessionId;

    if (!sessionMessagesMap[sessionId] || sessionMessagesMap[sessionId].length === 0) {
        await loadSessionMessages(sessionId);
    } else {
        renderMessagesForSession(sessionId);
    }

    refreshTodos(sessionId);
}

// 渲染特定 Session 的消息列表
function renderMessagesForSession(sessionId) {
    const container = document.getElementById("messagesList");
    container.innerHTML = "";

    const msgs = sessionMessagesMap[sessionId] || [];

    if (msgs.length === 0) {
        container.innerHTML = `
            <div class="welcome-card">
                <h2>🚀 当前窗口: [${sessionId}] - 已就绪 (已启用磁盘历史落盘)</h2>
                <p>在此窗口进行的所有问答与工具调度都将自动落盘存至 data/sessions/ 目录，即使服务重启亦可随时恢复！右键标签即可删除窗口。</p>
                <div class="quick-prompts">
                    <button class="quick-btn" onclick="sendQuickPrompt('帮我查一下广州的天气，然后记一条出行待办')">
                        ☀️ 查广州天气并记待办
                    </button>
                    <button class="quick-btn" onclick="sendQuickPrompt('我今天需要写周报，帮我记一条写周报的待办事项')">
                        📝 记一条周报待办
                    </button>
                    <button class="quick-btn" onclick="sendQuickPrompt('计算 12 * (34 + 56) 等于多少')">
                        🧮 复杂数学计算测试
                    </button>
                </div>
            </div>
        `;
        return;
    }

    msgs.forEach(item => {
        if (item.role === "user") {
            appendUserBubbleDOM(item.content);
        } else if (item.role === "agent") {
            appendAgentCardDOM(item.response);
        }
    });

    scrollToBottom();
}

function initChatForm() {
    const form = document.getElementById("chatForm");
    const input = document.getElementById("userInput");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        input.value = "";
        await sendMessage(text);
    });
}

async function sendQuickPrompt(promptText) {
    await sendMessage(promptText);
}

// 核心：发送消息并联通后端 REST API
async function sendMessage(text) {
    const currentSession = activeSessionId;

    if (!sessionMessagesMap[currentSession]) {
        sessionMessagesMap[currentSession] = [];
    }
    sessionMessagesMap[currentSession].push({ role: "user", content: text });
    
    const container = document.getElementById("messagesList");
    if (container.querySelector(".welcome-card")) {
        container.innerHTML = "";
    }
    
    appendUserBubbleDOM(text);
    scrollToBottom();

    const loadingCard = createLoadingCardDOM();
    container.appendChild(loadingCard);
    scrollToBottom();

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: text,
                session_id: currentSession
            })
        });

        if (!response.ok) {
            const errJson = await response.json();
            throw new Error(errJson.error || `HTTP 错误: ${response.status}`);
        }

        const data = await response.json();
        loadingCard.remove();

        sessionMessagesMap[currentSession].push({ role: "agent", response: data });

        appendAgentCardDOM(data);
        scrollToBottom();

        // 自动更新当前 Session 的动态标题页签
        if (data.session_title) {
            const currentTab = document.querySelector(`.tab-btn[data-session="${currentSession}"] .tab-title-text`);
            if (currentTab) {
                currentTab.textContent = data.session_title;
            }
        }

        if (data.is_real_api) {
            updateStatusUI(true, data.model_used);
        }

        if (data.todos) {
            renderTodosDOM(data.todos);
        } else {
            refreshTodos(currentSession);
        }

    } catch (err) {
        console.error("调用 Agent API 失败:", err);
        loadingCard.remove();
        appendAgentCardDOM({
            final_answer: `❌ 后端 Agent 调用失败: ${err.message}。建议检查配置或查看后端日志。`,
            traces: []
        });
    }
}

function appendUserBubbleDOM(text) {
    const container = document.getElementById("messagesList");
    const row = document.createElement("div");
    row.className = "msg-row user-msg";
    row.innerHTML = `<div class="user-bubble">${escapeHTML(text)}</div>`;
    container.appendChild(row);
}

function appendAgentCardDOM(agentData) {
    const container = document.getElementById("messagesList");
    const row = document.createElement("div");
    row.className = "msg-row agent-msg";

    let thoughtHTML = "";
    let toolCallsHTML = "";

    if (agentData.traces && agentData.traces.length > 0) {
        agentData.traces.forEach(step => {
            if (step.thought) {
                thoughtHTML += `
                    <div class="thought-box">
                        <div class="thought-title">💭 Step ${step.step} Agent 思考过程</div>
                        <div>${escapeHTML(step.thought)}</div>
                    </div>
                `;
            }

            if (step.tool_calls && step.tool_calls.length > 0) {
                step.tool_calls.forEach(tc => {
                    const res = step.tool_results ? step.tool_results.find(r => r.call_id === tc.id) : null;
                    const obsOutput = res ? res.output : "无返回结果";
                    const execTime = res && typeof res.execution_time === "number" ? ` <span style="font-size:0.75rem; opacity:0.7; font-weight:normal;">(${res.execution_time.toFixed(2)}s)</span>` : '';
                    const isError = res && res.is_error;
                    const obsClass = isError ? "tool-obs error-obs" : "tool-obs";
                    const statusTag = isError ? '<span style="color:#ef4444; font-weight:bold;"> [执行失败]</span>' : '';

                    toolCallsHTML += `
                        <div class="tool-calls-box">
                            <div class="tool-call-header">
                                <span>🛠️ 工具调用: <strong>${escapeHTML(tc.name)}</strong>${execTime}${statusTag}</span>
                            </div>
                            <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 0.2rem;">
                                参数: <code>${escapeHTML(JSON.stringify(tc.arguments))}</code>
                            </div>
                            <div class="${obsClass}">📥 Observation: ${escapeHTML(obsOutput)}</div>
                        </div>
                    `;
                });
            }
        });
    }

    const modelInfoTag = agentData.model_used ? `<div class="model-tag-inline">Model: ${escapeHTML(agentData.model_used)} (${agentData.is_real_api ? 'Real API' : 'Mock Mode'})</div>` : '';

    const card = document.createElement("div");
    card.className = "agent-card";
    card.innerHTML = `
        ${thoughtHTML}
        ${toolCallsHTML}
        <div class="answer-box">
            ${escapeHTML(agentData.final_answer).replace(/\n/g, '<br>')}
        </div>
        ${modelInfoTag}
    `;

    row.appendChild(card);
    container.appendChild(row);
}

function createLoadingCardDOM() {
    const row = document.createElement("div");
    row.className = "msg-row agent-msg";
    row.innerHTML = `
        <div class="agent-card" style="opacity: 0.8;">
            <div class="thought-box" style="border-left-color: var(--accent-blue);">
                <div class="thought-title" style="color: var(--accent-blue);">⚡ Agent 正在推理决策并选择工具中...</div>
            </div>
        </div>
    `;
    return row;
}

function initConfigModal() {
    const modal = document.getElementById("configModal");
    const openBtn = document.getElementById("openConfigBtn");
    const closeBtn = document.getElementById("closeConfigBtn");
    const form = document.getElementById("configForm");
    const toggleKeyBtn = document.getElementById("toggleKeyBtn");
    const keyInput = document.getElementById("cfgApiKey");
    const tempInput = document.getElementById("cfgTemp");
    const tempVal = document.getElementById("tempVal");
    const clearBtn = document.getElementById("clearKeyBtn");

    openBtn.addEventListener("click", () => modal.classList.add("active"));
    closeBtn.addEventListener("click", () => modal.classList.remove("active"));
    
    modal.addEventListener("click", (e) => {
        if (e.target === modal) modal.classList.remove("active");
    });

    toggleKeyBtn.addEventListener("click", () => {
        if (keyInput.type === "password") {
            keyInput.type = "text";
            toggleKeyBtn.textContent = "🙈";
        } else {
            keyInput.type = "password";
            toggleKeyBtn.textContent = "👁️";
        }
    });

    tempInput.addEventListener("input", () => {
        tempVal.textContent = tempInput.value;
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const apiKey = document.getElementById("cfgApiKey").value.trim();
        const baseUrl = document.getElementById("cfgBaseUrl").value.trim();
        const model = document.getElementById("cfgModel").value.trim() || "gpt-4o-mini";
        const temp = parseFloat(tempInput.value);

        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    api_key: apiKey,
                    base_url: baseUrl,
                    model: model,
                    temperature: temp
                })
            });

            const data = await res.json();
            if (res.ok) {
                alert(`✅ 大模型 API 配置更新成功并已保存至 .env 文件！连接 Model: ${data.model}`);
                modal.classList.remove("active");
                updateStatusUI(data.is_real_api, data.model);
            } else {
                alert(`❌ 配置更新失败: ${data.error}`);
            }
        } catch (err) {
            alert(`❌ 更新出错: ${err.message}`);
        }
    });

    clearBtn.addEventListener("click", async () => {
        document.getElementById("cfgApiKey").value = "";
        try {
            await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ api_key: "mock-api-key" })
            });
            alert("已切回 Mock 调试模式！");
            modal.classList.remove("active");
            updateStatusUI(false, "gpt-4o-mini");
        } catch (e) {
            console.error(e);
        }
    });
}

function applyPreset(baseUrl, model) {
    document.getElementById("cfgBaseUrl").value = baseUrl;
    document.getElementById("cfgModel").value = model;
}

async function fetchCurrentConfig() {
    try {
        const res = await fetch("/api/config");
        if (res.ok) {
            const data = await res.json();
            if (data.api_key_set && data.masked_key) {
                document.getElementById("cfgApiKey").value = "******";
            }
            if (data.base_url) {
                document.getElementById("cfgBaseUrl").value = data.base_url;
            }
            if (data.model) {
                document.getElementById("cfgModel").value = data.model;
            }
            if (data.temperature) {
                document.getElementById("cfgTemp").value = data.temperature;
                document.getElementById("tempVal").textContent = data.temperature;
            }
            updateStatusUI(data.is_real_api, data.model);
        }
    } catch (e) {
        console.warn("无法拉取大模型配置:", e);
    }
}

function updateStatusUI(isRealApi, modelName) {
    const statusDot = document.getElementById("statusDot");
    const statusText = document.getElementById("statusText");
    const activeModelTag = document.getElementById("activeModelTag");
    const modelModeDesc = document.getElementById("modelModeDesc");

    activeModelTag.textContent = modelName || "gpt-4o-mini";

    if (isRealApi) {
        statusDot.className = "status-dot real-api";
        statusText.textContent = `Real API: ${modelName}`;
        modelModeDesc.textContent = `已链接真实大模型 (${modelName})。配置已自动写入 .env 文件。`;
    } else {
        statusDot.className = "status-dot online";
        statusText.textContent = "Mode: Mock 模式";
        modelModeDesc.textContent = "当前处于 Mock 调试模式。配置 API Key 后可自动保存并开启真实调用。";
    }
}

async function refreshTodos(sessionId) {
    try {
        const res = await fetch(`/api/todos?session_id=${sessionId}`);
        if (res.ok) {
            const data = await res.json();
            renderTodosDOM(data.todos || []);
        }
    } catch (e) {
        console.warn("无法刷新 Todo 列表:", e);
    }
}

function renderTodosDOM(todos) {
    const listContainer = document.getElementById("todoList");
    listContainer.innerHTML = "";

    if (!todos || todos.length === 0) {
        listContainer.innerHTML = `<div class="empty-state">当前窗口暂无待办事项</div>`;
        return;
    }

    todos.forEach((item, idx) => {
        const div = document.createElement("div");
        div.className = "todo-item";
        div.innerHTML = `<span>${idx + 1}.</span> <span>${escapeHTML(item)}</span>`;
        listContainer.appendChild(div);
    });
}

function scrollToBottom() {
    const container = document.getElementById("messagesList");
    container.scrollTop = container.scrollHeight;
}

function escapeHTML(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
