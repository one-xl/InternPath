import { useState, useEffect } from "react";
import {
  adminFetchUsers,
  adminFetchConfigs,
  adminCreateConfig,
  adminUpdateConfig,
  adminAssignConfig,
  adminRevokeConfig,
  adminGetAssignments,
  adminGetUsageSummary,
  adminGetUsageLogs,
  AdminUser,
  AdminModelConfig,
  UsageSummary,
  UsageLog,
} from "../services/adminService";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

type AdminTab = "users" | "configs" | "assignments" | "statistics" | "logs";

export function AdminPage() {
  const [activeTab, setActiveTab] = useState<AdminTab>("users");
  
  // State
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [configs, setConfigs] = useState<AdminModelConfig[]>([]);
  const [usageSummary, setUsageSummary] = useState<UsageSummary | null>(null);
  const [usageLogs, setUsageLogs] = useState<UsageLog[]>([]);
  const [totalLogsCount, setTotalLogsCount] = useState(0);
  const [logsPage, setLogsPage] = useState(1);
  const [logsPageSize] = useState(15);
  
  // Filter States
  const [filterProvider, setFilterProvider] = useState("");
  const [filterModelId, setFilterModelId] = useState("");
  const [filterSuccess, setFilterSuccess] = useState<boolean | undefined>(undefined);
  const [filterUserId, setFilterUserId] = useState<string | number>("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form Modals States
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  const [selectedConfigId, setSelectedConfigId] = useState<string | null>(null);
  
  // Config Form Fields
  const [formProvider, setFormProvider] = useState("gemini");
  const [formModelId, setFormModelId] = useState("gemini-2.5-flash");
  const [formName, setFormName] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formTemp, setFormTemp] = useState("0.7");
  const [formMaxTokens, setFormMaxTokens] = useState("2048");

  // Assignment Modal States
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedConfigForAssign, setSelectedConfigForAssign] = useState<AdminModelConfig | null>(null);
  const [assignedUsers, setAssignedUsers] = useState<any[]>([]);
  const [assignTargetUserIds, setAssignTargetUserIds] = useState<Array<string | number>>([]);

  // Load Initial Data based on active tab
  useEffect(() => {
    loadTabData();
  }, [activeTab, logsPage, filterProvider, filterModelId, filterSuccess, filterUserId]);

  async function loadTabData() {
    setLoading(true);
    setError(null);
    try {
      if (activeTab === "users") {
        const u = await adminFetchUsers();
        setUsers(u);
      } else if (activeTab === "configs") {
        const c = await adminFetchConfigs();
        setConfigs(c);
      } else if (activeTab === "assignments") {
        const c = await adminFetchConfigs();
        setConfigs(c);
      } else if (activeTab === "statistics") {
        const summary = await adminGetUsageSummary({
          provider: filterProvider || undefined,
          modelId: filterModelId || undefined,
          userId: filterUserId || undefined,
        });
        setUsageSummary(summary);
      } else if (activeTab === "logs") {
        const res = await adminGetUsageLogs({
          provider: filterProvider || undefined,
          modelId: filterModelId || undefined,
          success: filterSuccess,
          userId: filterUserId || undefined,
          page: logsPage,
          pageSize: logsPageSize,
        });
        setUsageLogs(res.logs);
        setTotalLogsCount(res.totalCount);
        // Load users to filter
        const u = await adminFetchUsers();
        setUsers(u);
      }
    } catch (err: any) {
      setError(err.message || "加载数据失败，请重试。");
    } finally {
      setLoading(false);
    }
  }

  // Handle Save Config
  async function handleSaveConfig(e: React.FormEvent) {
    e.preventDefault();
    if (!formProvider || !formModelId || !formName) {
      alert("请填写必填项");
      return;
    }
    setLoading(true);
    try {
      const extraJson: Record<string, any> = {
        name: formName,
      };
      if (formBaseUrl) extraJson.baseUrl = formBaseUrl.trim();
      if (formTemp) extraJson.temperature = parseFloat(formTemp);
      if (formMaxTokens) extraJson.maxOutputTokens = parseInt(formMaxTokens, 10);

      if (isEditMode && selectedConfigId) {
        await adminUpdateConfig(selectedConfigId, {
          provider: formProvider,
          modelId: formModelId.trim(),
          name: formName.trim(),
          apiKey: formApiKey || undefined,
          enabled: formEnabled,
          config_json: extraJson,
        });
        alert("模型配置修改成功");
      } else {
        if (!formApiKey) {
          alert("新建配置时必须输入 API Key");
          setLoading(false);
          return;
        }
        await adminCreateConfig({
          provider: formProvider,
          modelId: formModelId.trim(),
          name: formName.trim(),
          apiKey: formApiKey.trim(),
          enabled: formEnabled,
          config_json: extraJson,
        });
        alert("模型配置创建成功");
      }
      setShowConfigModal(false);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "保存失败，请检查参数");
    } finally {
      setLoading(false);
    }
  }

  // Open Edit Modal
  function openEditConfig(cfg: AdminModelConfig) {
    setIsEditMode(true);
    setSelectedConfigId(cfg.id);
    setFormProvider(cfg.provider);
    setFormModelId(cfg.modelId);
    setFormName(cfg.name);
    setFormApiKey(""); // Don't show raw key, leave empty to keep unchanged
    setFormEnabled(cfg.enabled);
    setFormBaseUrl(cfg.baseUrl || "");
    setFormTemp(cfg.temperature !== undefined ? String(cfg.temperature) : "0.7");
    setFormMaxTokens(cfg.maxOutputTokens !== undefined ? String(cfg.maxOutputTokens) : "2048");
    setShowConfigModal(true);
  }

  // Toggle Config Enabled Status Directly
  async function toggleConfigStatus(cfg: AdminModelConfig) {
    setLoading(true);
    try {
      await adminUpdateConfig(cfg.id, {
        provider: cfg.provider,
        modelId: cfg.modelId,
        name: cfg.name,
        enabled: !cfg.enabled,
      });
      alert(cfg.enabled ? "已成功停用该配置" : "已成功启用该配置");
      loadTabData();
    } catch (err: any) {
      alert(err.message || "操作失败");
    } finally {
      setLoading(false);
    }
  }

  // Load Assignments for Config
  async function openAssignModal(cfg: AdminModelConfig) {
    setSelectedConfigForAssign(cfg);
    setLoading(true);
    try {
      const data = await adminGetAssignments(cfg.id);
      setAssignedUsers(data);
      const userList = await adminFetchUsers();
      setUsers(userList);
      setAssignTargetUserIds([]);
      setShowAssignModal(true);
    } catch (err: any) {
      alert(err.message || "获取分配列表失败");
    } finally {
      setLoading(false);
    }
  }

  // Submit Assignment
  async function handleAssignConfig() {
    if (!selectedConfigForAssign) return;
    if (assignTargetUserIds.length === 0) {
      alert("请选择至少一个需要分发配置的目标用户");
      return;
    }
    setLoading(true);
    try {
      await adminAssignConfig(selectedConfigForAssign.id, assignTargetUserIds);
      alert("分配配置成功！");
      // Reload assignments
      const data = await adminGetAssignments(selectedConfigForAssign.id);
      setAssignedUsers(data);
      setAssignTargetUserIds([]);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "分配失败");
    } finally {
      setLoading(false);
    }
  }

  // Submit Revocation
  async function handleRevokeConfig(userId: string | number) {
    if (!selectedConfigForAssign) return;
    if (!window.confirm("确定撤回该用户对本模型配置的访问权限吗？")) return;
    setLoading(true);
    try {
      await adminRevokeConfig(selectedConfigForAssign.id, [userId]);
      alert("已成功撤回分配！");
      const data = await adminGetAssignments(selectedConfigForAssign.id);
      setAssignedUsers(data);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "撤回失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-stack" style={{ maxWidth: "1200px", margin: "0 auto", paddingBottom: "50px" }}>
      <div className="page-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <span className="section-kicker" style={{ background: "linear-gradient(90deg, #f59e0b, #d97706)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            👑 系统管理
          </span>
          <h2 style={{ fontSize: "24px", color: "#fff", fontWeight: "800", marginTop: "8px" }}>管理员控制台</h2>
          <p style={{ color: "rgba(255, 255, 255, 0.6)", fontSize: "13px", marginTop: "4px" }}>
            管理服务器端 API 密钥安全分发，配置多用户模型间接调用，并审计资源消耗明细。
          </p>
        </div>
      </div>

      {/* Tabs Selector */}
      <div
        className="glass-tabs"
        style={{
          display: "flex",
          gap: "4px",
          background: "rgba(255, 255, 255, 0.03)",
          border: "1px solid rgba(255, 255, 255, 0.05)",
          padding: "4px",
          borderRadius: "var(--radius-lg)",
          width: "fit-content",
          marginBottom: "20px"
        }}
      >
        {[
          { key: "users", label: "用户管理" },
          { key: "configs", label: "模型配置" },
          { key: "assignments", label: "配置分配" },
          { key: "statistics", label: "调用统计" },
          { key: "logs", label: "调用日志" },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => {
              setActiveTab(tab.key as AdminTab);
              setError(null);
            }}
            style={{
              background: activeTab === tab.key ? "rgba(255, 255, 255, 0.1)" : "transparent",
              color: activeTab === tab.key ? "#fff" : "rgba(255, 255, 255, 0.6)",
              border: "none",
              padding: "8px 16px",
              borderRadius: "var(--radius-md)",
              fontSize: "13px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 200ms ease"
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "var(--radius-md)", padding: "12px", color: "#f87171", fontSize: "13px", marginBottom: "20px" }}>
          ⚠️ {error}
        </div>
      )}

      {/* 1. Users Tab */}
      {activeTab === "users" && (
        <Card title="系统注册用户" description="管理系统注册的用户、角色权限、关联设备数以及整体调用明细。">
          <div style={{ overflowX: "auto" }}>
            <table className="admin-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", color: "rgba(255, 255, 255, 0.85)" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", textAlign: "left", color: "rgba(255, 255, 255, 0.5)" }}>
                  <th style={{ padding: "12px 8px" }}>用户</th>
                  <th style={{ padding: "12px 8px" }}>角色</th>
                  <th style={{ padding: "12px 8px" }}>已分配模型</th>
                  <th style={{ padding: "12px 8px" }}>模型调用次数</th>
                  <th style={{ padding: "12px 8px" }}>注册时间</th>
                  <th style={{ padding: "12px 8px" }}>最近活动</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.04)" }}>
                    <td style={{ padding: "12px 8px", fontWeight: 600, color: "#fff" }}>{u.username}</td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{
                        background: u.role === "admin" ? "rgba(245, 158, 11, 0.15)" : "rgba(255, 255, 255, 0.06)",
                        color: u.role === "admin" ? "#f59e0b" : "rgba(255, 255, 255, 0.7)",
                        padding: "2px 8px",
                        borderRadius: "10px",
                        fontSize: "11px",
                        fontWeight: 700
                      }}>
                        {u.role === "admin" ? "管理员" : "用户"}
                      </span>
                    </td>
                    <td style={{ padding: "12px 8px" }}>
                      {u.assigned_models && u.assigned_models.length > 0 ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                          {u.assigned_models.map((m, idx) => (
                            <span key={idx} style={{ background: "rgba(59, 130, 246, 0.12)", color: "#60a5fa", padding: "1px 6px", borderRadius: "4px", fontSize: "11px" }}>
                              {m}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span style={{ color: "rgba(255, 255, 255, 0.3)" }}>无</span>
                      )}
                    </td>
                    <td style={{ padding: "12px 8px", fontWeight: "bold" }}>{u.usage_count} 次</td>
                    <td style={{ padding: "12px 8px", color: "rgba(255, 255, 255, 0.5)" }}>{new Date(u.created_at).toLocaleString("zh-CN")}</td>
                    <td style={{ padding: "12px 8px", color: "rgba(255, 255, 255, 0.5)" }}>{u.last_login ? new Date(u.last_login).toLocaleString("zh-CN") : "暂无活跃记录"}</td>
                  </tr>
                ))}
                {!users.length && !loading && (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: "30px", color: "rgba(255,255,255,0.4)" }}>无用户记录。</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* 2. Model Configs Tab */}
      {activeTab === "configs" && (
        <Card
          title="管理员托管配置"
          description="在此创建和维护服务器端托管的 API 密钥与模型。用户可以在配置分配页面中被赋予这些模型的使用权。"
          action={
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                setIsEditMode(false);
                setSelectedConfigId(null);
                setFormProvider("gemini");
                setFormModelId("gemini-2.5-flash");
                setFormName("");
                setFormApiKey("");
                setFormEnabled(true);
                setFormBaseUrl("");
                setFormTemp("0.7");
                setFormMaxTokens("2048");
                setShowConfigModal(true);
              }}
            >
              新建管理员配置
            </Button>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "16px", marginTop: "10px" }}>
            {configs.map((cfg) => (
              <div
                key={cfg.id}
                style={{
                  background: "rgba(255, 255, 255, 0.02)",
                  border: "1px solid rgba(255, 255, 255, 0.05)",
                  borderRadius: "var(--radius-lg)",
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  opacity: cfg.enabled ? 1 : 0.65
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span style={{
                      background: "rgba(255, 255, 255, 0.05)",
                      color: "rgba(255, 255, 255, 0.8)",
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "6px",
                      fontWeight: "bold",
                      textTransform: "uppercase"
                    }}>
                      {cfg.provider}
                    </span>
                    <span style={{ fontSize: "11px", color: cfg.enabled ? "#10b981" : "#ef4444", fontWeight: 700 }}>
                      ● {cfg.enabled ? "已启用" : "已停用"}
                    </span>
                  </div>
                  <h4 style={{ color: "#fff", fontSize: "16px", fontWeight: "700", marginTop: "10px" }}>{cfg.name}</h4>
                  <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "12px", marginTop: "2px", fontFamily: "monospace" }}>{cfg.modelId}</p>
                  
                  <div style={{ marginTop: "14px", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: "10px", display: "flex", flexDirection: "column", gap: "6px", fontSize: "12px", color: "rgba(255,255,255,0.6)" }}>
                    <div>
                      <span>已分配用户数：</span>
                      <strong style={{ color: "#60a5fa" }}>{cfg.assignment_count} 人</strong>
                    </div>
                    <div>
                      <span>创建时间：</span>
                      <span>{new Date(cfg.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", gap: "8px", marginTop: "18px" }}>
                  <Button type="button" variant="secondary" onClick={() => openEditConfig(cfg)}>
                    编辑配置
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => toggleConfigStatus(cfg)}
                    style={{ color: cfg.enabled ? "#f87171" : "#34d399", background: "rgba(255,255,255,0.02)" }}
                  >
                    {cfg.enabled ? "停用" : "启用"}
                  </Button>
                </div>
              </div>
            ))}
            {!configs.length && !loading && (
              <p style={{ gridColumn: "1/-1", color: "rgba(255, 255, 255, 0.4)", textAlign: "center", padding: "40px 0" }}>暂无任何管理员模型配置，请点击右上角新建。</p>
            )}
          </div>
        </Card>
      )}

      {/* 3. Config Assignments Tab */}
      {activeTab === "assignments" && (
        <Card title="模型分发与分配" description="在此将创建好的管理员托管配置分发给所选的普通用户，或者回收他们的使用权限。">
          <div style={{ overflowX: "auto" }}>
            <table className="admin-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", color: "rgba(255, 255, 255, 0.85)" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", textAlign: "left", color: "rgba(255, 255, 255, 0.5)" }}>
                  <th style={{ padding: "12px 8px" }}>配置名称</th>
                  <th style={{ padding: "12px 8px" }}>提供商</th>
                  <th style={{ padding: "12px 8px" }}>模型标识</th>
                  <th style={{ padding: "12px 8px" }}>已分发用户数</th>
                  <th style={{ padding: "12px 8px" }}>用途与状态</th>
                  <th style={{ padding: "12px 8px", textAlign: "right" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {configs.map((cfg) => (
                  <tr key={cfg.id} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.04)" }}>
                    <td style={{ padding: "12px 8px", fontWeight: 600, color: "#fff" }}>{cfg.name}</td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{ background: "rgba(255,255,255,0.05)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px" }}>{cfg.provider}</span>
                    </td>
                    <td style={{ padding: "12px 8px", fontFamily: "monospace", color: "rgba(255,255,255,0.6)" }}>{cfg.modelId}</td>
                    <td style={{ padding: "12px 8px", fontWeight: "bold", color: "#60a5fa" }}>{cfg.assignment_count} 人</td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{ color: cfg.enabled ? "#34d399" : "#ef4444" }}>● {cfg.enabled ? "服务正常" : "已失效"}</span>
                    </td>
                    <td style={{ padding: "12px 8px", textAlign: "right" }}>
                      <Button type="button" variant="primary" onClick={() => openAssignModal(cfg)}>
                        配置分发人员
                      </Button>
                    </td>
                  </tr>
                ))}
                {!configs.length && !loading && (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: "30px", color: "rgba(255,255,255,0.4)" }}>无模型配置记录。请先在“模型配置”标签中新建。</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* 4. Statistics Tab */}
      {activeTab === "statistics" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Filters Bar */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "12px",
              background: "rgba(255, 255, 255, 0.02)",
              border: "1px solid rgba(255, 255, 255, 0.05)",
              borderRadius: "var(--radius-lg)",
              padding: "12px 16px",
              alignItems: "center"
            }}
          >
            <span style={{ fontSize: "13px", color: "rgba(255,255,255,0.6)", fontWeight: 700 }}>🔍 过滤条件：</span>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <select
                value={filterProvider}
                onChange={(e) => setFilterProvider(e.target.value)}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px" }}
              >
                <option value="">所有提供商</option>
                <option value="gemini">Gemini</option>
                <option value="openai-compatible">OpenAI-Compatible</option>
                <option value="doubao">Doubao / Volcano</option>
                <option value="custom">Custom</option>
              </select>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <input
                type="text"
                value={filterModelId}
                placeholder="过滤 Model ID"
                onChange={(e) => setFilterModelId(e.target.value)}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px", width: "150px" }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <input
                type="text"
                value={String(filterUserId)}
                placeholder="过滤 User ID"
                onChange={(e) => setFilterUserId(e.target.value)}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px", width: "150px" }}
              />
            </div>
            
            <Button type="button" variant="secondary" onClick={() => {
              setFilterProvider("");
              setFilterModelId("");
              setFilterUserId("");
            }}>
              重置
            </Button>
          </div>

          {/* Stats Summary Cards */}
          {usageSummary && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
              <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: "var(--radius-lg)", padding: "16px" }}>
                <span style={{ fontSize: "12px", color: "rgba(255,255,255,0.4)" }}>总调用次数</span>
                <h3 style={{ fontSize: "28px", color: "#fff", fontWeight: "800", marginTop: "6px" }}>{usageSummary.totalCalls} 次</h3>
              </div>
              <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: "var(--radius-lg)", padding: "16px" }}>
                <span style={{ fontSize: "12px", color: "rgba(255,255,255,0.4)" }}>成功次数 / 失败率</span>
                <h3 style={{ fontSize: "28px", color: "#34d399", fontWeight: "800", marginTop: "6px" }}>
                  {usageSummary.successCalls} <span style={{ fontSize: "14px", color: "#f87171", fontWeight: "normal" }}>/ {usageSummary.totalCalls > 0 ? ((usageSummary.failedCalls / usageSummary.totalCalls) * 100).toFixed(1) : 0}% 失败</span>
                </h3>
              </div>
              <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: "var(--radius-lg)", padding: "16px" }}>
                <span style={{ fontSize: "12px", color: "rgba(255,255,255,0.4)" }}>平均延迟时长</span>
                <h3 style={{ fontSize: "28px", color: "#fbbf24", fontWeight: "800", marginTop: "6px" }}>{(usageSummary.avgLatency / 1000).toFixed(2)} 秒</h3>
              </div>
              <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: "var(--radius-lg)", padding: "16px" }}>
                <span style={{ fontSize: "12px", color: "rgba(255,255,255,0.4)" }}>总消费 Token 计数</span>
                <h3 style={{ fontSize: "28px", color: "#60a5fa", fontWeight: "800", marginTop: "6px" }}>{usageSummary.totalTokens.toLocaleString()}</h3>
                <span style={{ fontSize: "11px", color: "rgba(255,255,255,0.4)" }}>入 {usageSummary.totalPromptTokens.toLocaleString()} / 出 {usageSummary.totalCompletionTokens.toLocaleString()}</span>
              </div>
            </div>
          )}

          {/* Detailed Lists */}
          {usageSummary && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px" }}>
              <Card title="按用户统计">
                <table style={{ width: "100%", fontSize: "12px", color: "rgba(255,255,255,0.85)" }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "rgba(255,255,255,0.4)" }}>
                      <th style={{ padding: "6px 0" }}>用户名</th>
                      <th style={{ padding: "6px 0", textAlign: "right" }}>调用频次</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageSummary.byUser.map((u, i) => (
                      <tr key={i}>
                        <td style={{ padding: "6px 0", fontWeight: 600 }}>{u.username}</td>
                        <td style={{ padding: "6px 0", textAlign: "right", fontWeight: "bold" }}>{u.count} 次</td>
                      </tr>
                    ))}
                    {!usageSummary.byUser.length && (
                      <tr>
                        <td colSpan={2} style={{ textAlign: "center", padding: "15px", color: "rgba(255,255,255,0.3)" }}>暂无记录。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Card>

              <Card title="按模型统计">
                <table style={{ width: "100%", fontSize: "12px", color: "rgba(255,255,255,0.85)" }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "rgba(255,255,255,0.4)" }}>
                      <th style={{ padding: "6px 0" }}>模型 ID</th>
                      <th style={{ padding: "6px 0", textAlign: "right" }}>调用频次</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usageSummary.byModel.map((m, i) => (
                      <tr key={i}>
                        <td style={{ padding: "6px 0", fontFamily: "monospace" }}>{m.modelId}</td>
                        <td style={{ padding: "6px 0", textAlign: "right", fontWeight: "bold" }}>{m.count} 次</td>
                      </tr>
                    ))}
                    {!usageSummary.byModel.length && (
                      <tr>
                        <td colSpan={2} style={{ textAlign: "center", padding: "15px", color: "rgba(255,255,255,0.3)" }}>暂无记录。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Card>

              <div style={{ gridColumn: "1/-1" }}>
                <Card title="按日期统计">
                  <table style={{ width: "100%", fontSize: "12px", color: "rgba(255,255,255,0.85)" }}>
                    <thead>
                      <tr style={{ textAlign: "left", color: "rgba(255,255,255,0.4)" }}>
                        <th style={{ padding: "6px 0" }}>日期</th>
                        <th style={{ padding: "6px 0", textAlign: "right" }}>单日调用次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usageSummary.byDay.map((d, i) => (
                        <tr key={i}>
                          <td style={{ padding: "6px 0" }}>{d.day}</td>
                          <td style={{ padding: "6px 0", textAlign: "right", fontWeight: "bold" }}>{d.count} 次</td>
                        </tr>
                      ))}
                      {!usageSummary.byDay.length && (
                        <tr>
                          <td colSpan={2} style={{ textAlign: "center", padding: "15px", color: "rgba(255,255,255,0.3)" }}>暂无记录。</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </Card>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 5. Usage Logs Tab */}
      {activeTab === "logs" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Filters Bar */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "12px",
              background: "rgba(255, 255, 255, 0.02)",
              border: "1px solid rgba(255, 255, 255, 0.05)",
              borderRadius: "var(--radius-lg)",
              padding: "12px 16px",
              alignItems: "center"
            }}
          >
            <span style={{ fontSize: "13px", color: "rgba(255,255,255,0.6)", fontWeight: 700 }}>🔍 日志筛选：</span>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <select
                value={filterProvider}
                onChange={(e) => { setFilterProvider(e.target.value); setLogsPage(1); }}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px" }}
              >
                <option value="">所有提供商</option>
                <option value="gemini">Gemini</option>
                <option value="openai-compatible">OpenAI-Compatible</option>
                <option value="doubao">Doubao / Volcano</option>
                <option value="custom">Custom</option>
              </select>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <select
                value={filterSuccess === undefined ? "" : String(filterSuccess)}
                onChange={(e) => {
                  const val = e.target.value;
                  setFilterSuccess(val === "" ? undefined : val === "true");
                  setLogsPage(1);
                }}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px" }}
              >
                <option value="">所有状态</option>
                <option value="true">成功</option>
                <option value="false">失败</option>
              </select>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <select
                value={String(filterUserId)}
                onChange={(e) => { setFilterUserId(e.target.value); setLogsPage(1); }}
                style={{ background: "#1a1a1a", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "6px 12px", fontSize: "13px" }}
              >
                <option value="">所有用户</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{u.username}</option>
                ))}
              </select>
            </div>
            
            <Button type="button" variant="secondary" onClick={() => {
              setFilterProvider("");
              setFilterSuccess(undefined);
              setFilterUserId("");
              setLogsPage(1);
            }}>
              清空筛选
            </Button>
          </div>

          <Card title="调用审计日志" description="系统在调用外部大语言模型/向量化模型接口时，出于数据隐私，系统从不记录敏感文本，仅进行非敏感字段的元数据归档。">
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", color: "rgba(255,255,255,0.85)" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", textAlign: "left", color: "rgba(255, 255, 255, 0.4)" }}>
                    <th style={{ padding: "10px 6px" }}>时间</th>
                    <th style={{ padding: "10px 6px" }}>调用用户</th>
                    <th style={{ padding: "10px 6px" }}>所用配置</th>
                    <th style={{ padding: "10px 6px" }}>Provider</th>
                    <th style={{ padding: "10px 6px" }}>模型</th>
                    <th style={{ padding: "10px 6px" }}>耗时(ms)</th>
                    <th style={{ padding: "10px 6px" }}>状态</th>
                    <th style={{ padding: "10px 6px" }}>Token 消费</th>
                  </tr>
                </thead>
                <tbody>
                  {usageLogs.map((log) => (
                    <tr key={log.id} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.04)" }}>
                      <td style={{ padding: "10px 6px", color: "rgba(255,255,255,0.5)" }}>{new Date(log.createdAt).toLocaleString("zh-CN")}</td>
                      <td style={{ padding: "10px 6px", fontWeight: "bold" }}>{log.username}</td>
                      <td style={{ padding: "10px 6px" }}>{log.configName}</td>
                      <td style={{ padding: "10px 6px", textTransform: "uppercase" }}>{log.provider}</td>
                      <td style={{ padding: "10px 6px", fontFamily: "monospace" }}>{log.modelId}</td>
                      <td style={{ padding: "10px 6px" }}>{log.latencyMs}ms</td>
                      <td style={{ padding: "10px 6px" }}>
                        <span style={{ color: log.success ? "#34d399" : "#f87171", fontWeight: "bold" }}>
                          {log.success ? "成功" : "失败"}{log.errorType ? ` (${log.errorType})` : ""}
                        </span>
                      </td>
                      <td style={{ padding: "10px 6px" }}>
                        {log.totalTokens !== null ? (
                          <span>
                            <strong>{log.totalTokens}</strong> <span style={{ color: "rgba(255,255,255,0.4)" }}>({log.promptTokens}/{log.completionTokens || 0})</span>
                          </span>
                        ) : (
                          <span style={{ color: "rgba(255,255,255,0.3)" }}>字符计: {log.inputChars}/{log.outputChars}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!usageLogs.length && !loading && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", padding: "30px", color: "rgba(255,255,255,0.4)" }}>无调用日志。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalLogsCount > logsPageSize && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "20px", fontSize: "13px" }}>
                <span style={{ color: "rgba(255,255,255,0.5)" }}>共 {totalLogsCount} 条记录</span>
                <div style={{ display: "flex", gap: "8px" }}>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={logsPage === 1}
                    onClick={() => setLogsPage(prev => Math.max(prev - 1, 1))}
                  >
                    上一页
                  </Button>
                  <span style={{ padding: "6px 12px", background: "rgba(255,255,255,0.05)", borderRadius: "var(--radius-md)" }}>
                    {logsPage} / {Math.ceil(totalLogsCount / logsPageSize)}
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={logsPage * logsPageSize >= totalLogsCount}
                    onClick={() => setLogsPage(prev => prev + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* --- MODAL DIALOGS --- */}

      {/* Create / Edit Config Modal */}
      {showConfigModal && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", justifyContent: "center", alignItems: "center", zIndex: 1000 }}>
          <form onSubmit={handleSaveConfig} style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "450px", maxWidth: "90%", display: "flex", flexDirection: "column", gap: "16px" }}>
            <h3 style={{ color: "#fff", fontSize: "18px", fontWeight: "800" }}>{isEditMode ? "编辑管理员托管配置" : "新建管理员托管配置"}</h3>
            <p style={{ fontSize: "12px", color: "rgba(255,255,255,0.5)" }}>
              该配置的所有权属于管理员/系统本身，普通用户无法查看真实的 API 密钥。
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>提供商 (Provider) *</label>
              <select
                value={formProvider}
                onChange={(e) => {
                  setFormProvider(e.target.value);
                  if (e.target.value === "gemini") setFormModelId("gemini-2.5-flash");
                  else if (e.target.value === "doubao") setFormModelId("ep-m-20260416004638-52mb2");
                  else setFormModelId("");
                }}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              >
                <option value="gemini">Gemini</option>
                <option value="openai-compatible">OpenAI Compatible (如 DeepSeek / 豆包 Ark)</option>
                <option value="doubao">豆包 Text Embedding (向量模型)</option>
                <option value="custom">Custom (自定义结构)</option>
              </select>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>配置名称 (DisplayName) *</label>
              <input
                type="text"
                required
                value={formName}
                placeholder="如: 服务器托管 Gemini 极速分析"
                onChange={(e) => setFormName(e.target.value)}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>模型标识 (Model ID) *</label>
              <input
                type="text"
                required
                value={formModelId}
                placeholder="如: gemini-2.5-flash 或 ep-m-xxx"
                onChange={(e) => setFormModelId(e.target.value)}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>API 密钥 (API Key) {isEditMode && "(留空代表不修改)"} *</label>
              <input
                type="password"
                required={!isEditMode}
                value={formApiKey}
                placeholder={isEditMode ? "•••••••• (无需修改时留空)" : "填入真实 API 密钥，在库中加密存储"}
                onChange={(e) => setFormApiKey(e.target.value)}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              />
            </div>

            {formProvider === "openai-compatible" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>接口地址 (Base URL)</label>
                <input
                  type="text"
                  value={formBaseUrl}
                  placeholder="如: https://api.deepseek.com/v1"
                  onChange={(e) => setFormBaseUrl(e.target.value)}
                  style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
                />
              </div>
            )}

            <div style={{ display: "flex", gap: "10px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>温度 (Temperature)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={formTemp}
                  onChange={(e) => setFormTemp(e.target.value)}
                  style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>最大 Token (MaxTokens)</label>
                <input
                  type="number"
                  min="1"
                  value={formMaxTokens}
                  onChange={(e) => setFormMaxTokens(e.target.value)}
                  style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
                />
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
              <input
                type="checkbox"
                id="formEnabled"
                checked={formEnabled}
                onChange={(e) => setFormEnabled(e.target.checked)}
                style={{ width: "16px", height: "16px" }}
              />
              <label htmlFor="formEnabled" style={{ fontSize: "13px", color: "#fff", cursor: "pointer" }}>立即启用该配置</label>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "10px" }}>
              <Button type="button" variant="secondary" onClick={() => setShowConfigModal(false)}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={loading}>
                {loading ? "正在保存..." : "确认保存"}
              </Button>
            </div>
          </form>
        </div>
      )}

      {/* Assignment Control Modal */}
      {showAssignModal && selectedConfigForAssign && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", justifyContent: "center", alignItems: "center", zIndex: 1000 }}>
          <div style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "500px", maxWidth: "90%", display: "flex", flexDirection: "column", gap: "16px" }}>
            <h3 style={{ color: "#fff", fontSize: "18px", fontWeight: "800" }}>模型配置分发设置</h3>
            <div style={{ fontSize: "13px", background: "rgba(255,255,255,0.03)", padding: "12px", borderRadius: "var(--radius-md)" }}>
              <div style={{ color: "rgba(255,255,255,0.5)" }}>当前配置名称：</div>
              <strong style={{ color: "#fff", fontSize: "14px" }}>{selectedConfigForAssign.name}</strong>
              <div style={{ color: "rgba(255,255,255,0.4)", fontSize: "11px", marginTop: "2px", fontFamily: "monospace" }}>{selectedConfigForAssign.modelId}</div>
            </div>

            {/* List of currently assigned users */}
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <span style={{ fontSize: "12px", color: "rgba(255,255,255,0.5)", fontWeight: "bold" }}>当前拥有该模型访问权的用户：</span>
              <div style={{ maxHeight: "150px", overflowY: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "var(--radius-md)", background: "rgba(255,255,255,0.01)" }}>
                {assignedUsers.map((a) => (
                  <div key={a.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <span style={{ color: "#fff", fontSize: "13px" }}>{a.username}</span>
                    <button
                      type="button"
                      onClick={() => handleRevokeConfig(a.user_id)}
                      style={{ background: "transparent", border: "none", color: "#f87171", cursor: "pointer", fontSize: "12px", fontWeight: 700 }}
                    >
                      收回权限
                    </button>
                  </div>
                ))}
                {!assignedUsers.length && (
                  <div style={{ padding: "16px", textAlign: "center", color: "rgba(255,255,255,0.3)", fontSize: "13px" }}>尚未分配给任何用户。</div>
                )}
              </div>
            </div>

            {/* Form to assign to new users */}
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "12px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>选择并分发给新用户 (支持多选) *</label>
              
              <div style={{ maxHeight: "120px", overflowY: "auto", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", background: "#1e1e1e", padding: "8px" }}>
                {users
                  .filter((u) => !assignedUsers.some((a) => a.user_id === u.id))
                  .map((u) => (
                    <div key={u.id} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "4px 0" }}>
                      <input
                        type="checkbox"
                        id={`user-chk-${u.id}`}
                        checked={assignTargetUserIds.includes(u.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setAssignTargetUserIds(prev => [...prev, u.id]);
                          } else {
                            setAssignTargetUserIds(prev => prev.filter(id => id !== u.id));
                          }
                        }}
                      />
                      <label htmlFor={`user-chk-${u.id}`} style={{ color: "#fff", fontSize: "13px", cursor: "pointer" }}>{u.username}</label>
                    </div>
                  ))}
                {users.filter((u) => !assignedUsers.some((a) => a.user_id === u.id)).length === 0 && (
                  <div style={{ color: "rgba(255,255,255,0.3)", fontSize: "12px", textAlign: "center", padding: "10px" }}>所有用户均已拥有该模型访问权限。</div>
                )}
              </div>
            </div>

            <div style={{ fontSize: "11px", color: "#f59e0b", background: "rgba(245, 158, 11, 0.08)", border: "1px solid rgba(245, 158, 11, 0.2)", borderRadius: "6px", padding: "8px", lineHeight: "1.4" }}>
              💡 <strong>安全说明：</strong>分配后该用户可在前端通过后端间接调用此模型，但 API 密钥依旧留在服务端，用户绝对无法导出或查看到真实密钥。
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "10px" }}>
              <Button type="button" variant="secondary" onClick={() => setShowAssignModal(false)}>
                关闭
              </Button>
              <Button type="button" variant="primary" disabled={loading} onClick={handleAssignConfig}>
                确定分配
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
