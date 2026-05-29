import { useState, useEffect, useCallback, useMemo } from "react";
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
  adminGenerateTempAccounts,
  adminUpdateUserStatus,
  adminUpdateUserExpiry,
  adminUpdateUserGenerationLimit,
  adminDeleteUser,
  adminDeleteExpiredUsers,
  adminUpdateUsername,
  adminUpdateUserRemark,
  AdminUser,
  AdminModelConfig,
  UsageSummary,
  UsageLog,
  GeneratedAccount,
  // Announcements
  AdminAnnouncement,
  adminFetchAnnouncements,
  adminCreateAnnouncement,
  adminUpdateAnnouncement,
  adminDeleteAnnouncement
} from "../services/adminService";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { apiFetch } from "../services/apiClient";


type AdminTab = "users" | "configs" | "assignments" | "statistics" | "logs" | "announcements";

export function AdminPage() {
  const [activeTab, setActiveTab] = useState<AdminTab>("users");
  
  // State
  const [users, setUsers] = useState<AdminUser[]>([]);

  // Announcements States
  const [announcements, setAnnouncements] = useState<AdminAnnouncement[]>([]);
  const [showAnnounceModal, setShowAnnounceModal] = useState(false);
  const [editingAnnouncement, setEditingAnnouncement] = useState<AdminAnnouncement | null>(null);
  const [annTitle, setAnnTitle] = useState("");
  const [annContent, setAnnContent] = useState("");
  const [annStartTime, setAnnStartTime] = useState("");
  const [annEndTime, setAnnEndTime] = useState("");
  const [annTargetType, setAnnTargetType] = useState<'all' | 'specific'>("all");
  const [annTargetUsers, setAnnTargetUsers] = useState("");
  const [annType, setAnnType] = useState<'top' | 'popup'>("top");
  const [annShowBehavior, setAnnShowBehavior] = useState<'once' | 'every_login' | 'always'>("once");

  // Users selection & filtering inside announcement modal
  const [userSearchQuery, setUserSearchQuery] = useState("");
  const [userTypeFilter, setUserTypeFilter] = useState<'all' | 'temp' | 'permanent'>("all");
  const [userTimeFilter, setUserTimeFilter] = useState<'all' | 'today' | '3days' | '7days' | '30days'>("all");
  const [selectedUsernames, setSelectedUsernames] = useState<string[]>([]);

  // Filtered users for announcement specific target checklist
  const filteredUsersForTarget = useMemo(() => {
    return users.filter((u) => {
      // 1. Username filter
      if (userSearchQuery.trim() && !u.username.toLowerCase().includes(userSearchQuery.toLowerCase())) {
        return false;
      }
      
      // 2. User Type filter (temp has expires_at, permanent has expires_at == null)
      if (userTypeFilter === "temp" && !u.expires_at) {
        return false;
      }
      if (userTypeFilter === "permanent" && u.expires_at) {
        return false;
      }
      
      // 3. User Registration Time filter
      if (userTimeFilter !== "all") {
        const regDate = new Date(u.created_at);
        const now = new Date();
        const diffMs = now.getTime() - regDate.getTime();
        const diffDays = diffMs / (1000 * 60 * 60 * 24);
        
        if (userTimeFilter === "today" && diffDays > 1) {
          return false;
        }
        if (userTimeFilter === "3days" && diffDays > 3) {
          return false;
        }
        if (userTimeFilter === "7days" && diffDays > 7) {
          return false;
        }
        if (userTimeFilter === "30days" && diffDays > 30) {
          return false;
        }
      }
      
      return true;
    });
  }, [users, userSearchQuery, userTypeFilter, userTimeFilter]);

  const handleToggleSelectAllFiltered = () => {
    const allFilteredUsernames = filteredUsersForTarget.map(u => u.username);
    const areAllSelected = allFilteredUsernames.every(name => selectedUsernames.includes(name));
    
    if (areAllSelected) {
      setSelectedUsernames(prev => prev.filter(name => !allFilteredUsernames.includes(name)));
    } else {
      setSelectedUsernames(prev => {
        const merged = [...prev, ...allFilteredUsernames];
        return Array.from(new Set(merged));
      });
    }
  };

  const handleClearAllSelections = () => {
    setSelectedUsernames([]);
  };

  const loadAnnouncements = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await adminFetchAnnouncements();
      setAnnouncements(list);
    } catch (err: any) {
      setError(err.message || "获取公告列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "announcements") {
      loadAnnouncements();
    }
  }, [activeTab, loadAnnouncements]);

  const handleOpenCreateAnnounce = () => {
    setEditingAnnouncement(null);
    setAnnTitle("");
    setAnnContent("");
    
    const now = new Date();
    const future = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
    
    const formatLocal = (d: Date) => {
      const pad = (n: number) => n.toString().padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };
    
    setAnnStartTime(formatLocal(now));
    setAnnEndTime(formatLocal(future));
    setAnnTargetType("all");
    setAnnTargetUsers("");
    setAnnType("top");
    setAnnShowBehavior("once");
    setUserSearchQuery("");
    setUserTypeFilter("all");
    setUserTimeFilter("all");
    setSelectedUsernames([]);
    
    if (users.length === 0) {
      adminFetchUsers().then(setUsers).catch(err => console.error("Failed to load users for filter:", err));
    }
    setShowAnnounceModal(true);
  };

  const handleOpenEditAnnounce = (ann: AdminAnnouncement) => {
    setEditingAnnouncement(ann);
    setAnnTitle(ann.title);
    setAnnContent(ann.content);
    
    const formatISOToLocal = (isoStr: string) => {
      if (!isoStr) return "";
      return isoStr.substring(0, 16);
    };
    
    setAnnStartTime(formatISOToLocal(ann.start_time));
    setAnnEndTime(formatISOToLocal(ann.end_time));
    setAnnTargetType(ann.target_type);
    setAnnTargetUsers(ann.target_users || "");
    setAnnType(ann.announcement_type || "top");
    setAnnShowBehavior(ann.show_behavior || "once");
    setUserSearchQuery("");
    setUserTypeFilter("all");
    setUserTimeFilter("all");
    const usernames = ann.target_users ? ann.target_users.split(",").map(u => u.trim()).filter(Boolean) : [];
    setSelectedUsernames(usernames);

    if (users.length === 0) {
      adminFetchUsers().then(setUsers).catch(err => console.error("Failed to load users for filter:", err));
    }
    setShowAnnounceModal(true);
  };

  const handleSaveAnnouncement = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!annTitle.trim() || !annContent.trim() || !annStartTime || !annEndTime) {
      alert("请填写所有必填字段。");
      return;
    }
    
    const toISOTime = (localStr: string) => {
      return new Date(localStr).toISOString();
    };

    setLoading(true);
    setError(null);
    try {
      const targetUsersString = annTargetType === 'specific' ? selectedUsernames.join(",") : undefined;
      const payload = {
        title: annTitle,
        content: annContent,
        start_time: toISOTime(annStartTime),
        end_time: toISOTime(annEndTime),
        target_type: annTargetType,
        target_users: targetUsersString,
        announcement_type: annType,
        show_behavior: annShowBehavior
      };

      if (editingAnnouncement && editingAnnouncement.id) {
        await adminUpdateAnnouncement(editingAnnouncement.id, payload);
      } else {
        await adminCreateAnnouncement(payload);
      }
      
      setShowAnnounceModal(false);
      await loadAnnouncements();
    } catch (err: any) {
      setError(err.message || "保存公告失败。");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteAnnouncement = async (id: string) => {
    if (!window.confirm("确定要删除这条公告吗？删除后所有受众用户都将无法在顶部看到此通知。")) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await adminDeleteAnnouncement(id);
      await loadAnnouncements();
    } catch (err: any) {
      setError(err.message || "删除公告失败。");
      setLoading(false);
    }
  };
  const [currentUser, setCurrentUser] = useState<any | null>(null);
  
  // Temporary account generator state
  const [genDurationHours, setGenDurationHours] = useState<number>(24);
  const [genQuantity, setGenQuantity] = useState<number>(1);
  const [generatedAccounts, setGeneratedAccounts] = useState<GeneratedAccount[]>([]);
  const [generating, setGenerating] = useState(false);

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
  const [formProvider, setFormProvider] = useState("custom");
  const [formModelId, setFormModelId] = useState("");
  const [formName, setFormName] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formTemp, setFormTemp] = useState("0.7");
  const [formMaxTokens, setFormMaxTokens] = useState("2048");
  const [formCurl, setFormCurl] = useState("");

  function tokenizeCommandLine(cmd: string): string[] {
    const args: string[] = [];
    let current = "";
    let inDoubleQuote = false;
    let inSingleQuote = false;
    let escaped = false;

    // clean line continuations first
    const cleanCmd = cmd.replace(/\\\r?\n/g, ' ');

    for (let i = 0; i < cleanCmd.length; i++) {
      const char = cleanCmd[i];
      if (escaped) {
        current += char;
        escaped = false;
        continue;
      }

      if (char === '\\' && !inSingleQuote) {
        escaped = true;
        continue;
      }

      if (char === '"' && !inSingleQuote) {
        inDoubleQuote = !inDoubleQuote;
        continue;
      }

      if (char === "'" && !inDoubleQuote) {
        inSingleQuote = !inSingleQuote;
        continue;
      }

      if (/\s/.test(char) && !inDoubleQuote && !inSingleQuote) {
        if (current) {
          args.push(current);
          current = "";
        }
      } else {
        current += char;
      }
    }
    if (current) {
      args.push(current);
    }
    return args;
  }

  function handleImportFromCurl(curl: string) {
    if (!curl || !curl.trim()) return;

    let tokens: string[] = [];
    try {
      tokens = tokenizeCommandLine(curl);
    } catch (e) {
      console.warn("Failed to tokenize cURL:", e);
      return;
    }

    let rawUrl = "";
    const headers: Record<string, string> = {};
    let requestBodyStr = "";

    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i];
      const lowerToken = token.toLowerCase();

      // Check for URL
      if (token.startsWith("http://") || token.startsWith("https://")) {
        rawUrl = token;
      }

      // Check for Header options
      if ((token === "-H" || lowerToken === "--header") && i + 1 < tokens.length) {
        const headerVal = tokens[i + 1];
        const colonIdx = headerVal.indexOf(":");
        if (colonIdx > -1) {
          const name = headerVal.substring(0, colonIdx).trim().toLowerCase();
          const value = headerVal.substring(colonIdx + 1).trim();
          headers[name] = value;
        }
        i++; // skip next token
      }

      // Check for Data/Body options
      if (
        (token === "-d" ||
          lowerToken === "--data" ||
          lowerToken === "--data-raw" ||
          lowerToken === "--data-binary" ||
          lowerToken === "--data-ascii") &&
        i + 1 < tokens.length
      ) {
        requestBodyStr = tokens[i + 1];
        i++; // skip next token
      }
    }

    // Fallback if URL option didn't start with protocol directly (e.g. url inside single quotes without http prefix, or just not parsed)
    if (!rawUrl) {
      const urlToken = tokens.find(t => t.includes("://"));
      if (urlToken) {
        rawUrl = urlToken;
      }
    }

    // 2. Try to extract API Key from headers
    let apiKey = "";
    if (headers["authorization"]) {
      const authVal = headers["authorization"];
      if (authVal.toLowerCase().startsWith("bearer ")) {
        apiKey = authVal.substring(7).trim();
      } else {
        apiKey = authVal.trim();
      }
    } else {
      const keyHeader = Object.keys(headers).find(h => 
        h === "api-key" || h === "x-api-key" || h === "x-goog-api-key" || h === "api_key"
      );
      if (keyHeader) {
        apiKey = headers[keyHeader].trim();
      }
    }

    // 3. Extract request body JSON if present
    let modelId = "";
    let temp = "0.7";
    let maxTokens = "2048";

    if (requestBodyStr) {
      try {
        const body = JSON.parse(requestBodyStr);
        if (body.model) modelId = body.model;
        if (body.temperature !== undefined) temp = String(body.temperature);
        if (body.max_tokens !== undefined) maxTokens = String(body.max_tokens);
        else if (body.maxOutputTokens !== undefined) maxTokens = String(body.maxOutputTokens);
      } catch (e) {
        console.warn("Failed to parse JSON body from curl:", e);
      }
    }

    // 4. Derive Base URL (removing specific endpoints)
    let baseUrl = "";
    let provider = "";

    if (rawUrl) {
      try {
        // Clean any trailing symbols
        rawUrl = rawUrl.replace(/['",;)]+$/, "");
        const parsedUrl = new URL(rawUrl);
        const host = parsedUrl.origin;
        const pathname = parsedUrl.pathname;

        if (rawUrl.includes("generativelanguage.googleapis.com")) {
          provider = "custom";
          const modelsMatch = pathname.match(/\/models\/([^:/]+)/);
          if (modelsMatch && !modelId) {
            modelId = modelsMatch[1];
          }
          baseUrl = host + pathname.split("/models/")[0];
        } else {
          provider = "openai-compatible";
          if (rawUrl.includes("volces.com") || rawUrl.includes("ark.cn-beijing")) {
            provider = "doubao-multimodal";
          }
          
          let cleanPath = pathname;
          if (cleanPath.endsWith("/chat/completions")) {
            cleanPath = cleanPath.substring(0, cleanPath.length - 17);
          } else if (cleanPath.endsWith("/chat")) {
            cleanPath = cleanPath.substring(0, cleanPath.length - 5);
          } else if (cleanPath.endsWith("/embeddings/multimodal")) {
            cleanPath = cleanPath.substring(0, cleanPath.length - 22);
          } else if (cleanPath.endsWith("/embeddings")) {
            cleanPath = cleanPath.substring(0, cleanPath.length - 11);
          } else if (cleanPath.endsWith("/v1/chat/completions")) {
            cleanPath = cleanPath.substring(0, cleanPath.length - 20) + "/v1";
          }
          baseUrl = host + cleanPath;
        }
      } catch (err) {
        console.warn("Failed to parse URL from curl:", err);
      }
    }

    // Update state fields
    if (provider) setFormProvider(provider);
    if (baseUrl) setFormBaseUrl(baseUrl);
    if (modelId) setFormModelId(modelId);
    if (apiKey) setFormApiKey(apiKey);
    if (temp) setFormTemp(temp);
    if (maxTokens) setFormMaxTokens(maxTokens);

    // Guess a name if current name is empty
    if (modelId) {
      const capitalizedProvider = provider ? provider.toUpperCase() : "CUSTOM";
      setFormName(`托管 ${capitalizedProvider} ${modelId}`);
    }
  }

  // Assignment Modal States
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedConfigForAssign, setSelectedConfigForAssign] = useState<AdminModelConfig | null>(null);
  const [assignedUsers, setAssignedUsers] = useState<any[]>([]);
  const [assignTargetUserIds, setAssignTargetUserIds] = useState<Array<string | number>>([]);

  // Load self user on mount
  useEffect(() => {
    apiFetch<any>("/api/me")
      .then((user) => setCurrentUser(user))
      .catch((err) => console.error("Failed to load self info", err));
  }, []);

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
    setFormCurl("");
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

  // Generate temporary accounts
  async function handleGenerateTempAccounts() {
    setGenerating(true);
    try {
      const res = await adminGenerateTempAccounts(genDurationHours, genQuantity);
      setGeneratedAccounts(res);
      alert(`已成功生成 ${res.length} 个临时账号！`);
      loadTabData(); // refresh list
    } catch (err: any) {
      alert(err.message || "生成临时账号失败");
    } finally {
      setGenerating(false);
    }
  }
  // Robust clipboard copy fallback
  function handleCopyText(text: string, successMessage: string = "已复制到剪贴板！") {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text)
        .then(() => alert(successMessage))
        .catch(() => fallbackCopy(text, successMessage));
    } else {
      fallbackCopy(text, successMessage);
    }
  }

  function fallbackCopy(text: string, successMessage: string) {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const success = document.execCommand("copy");
      document.body.removeChild(textarea);
      if (success) {
        alert(successMessage + " (使用降级兼容方案)");
      } else {
        throw new Error();
      }
    } catch (e) {
      window.prompt("当前环境不支持自动复制，请手动复制以下内容：", text);
    }
  }

  // Toggle user active status
  async function handleToggleUserStatus(u: AdminUser) {
    if (currentUser && String(u.id) === String(currentUser.id)) {
      alert("您不能修改自己当前管理员账号的启用状态。");
      return;
    }
    const targetStatus = u.is_active === undefined ? false : !u.is_active;
    setLoading(true);
    try {
      await adminUpdateUserStatus(u.id, targetStatus);
      alert(`已成功${targetStatus ? "启用" : "禁用"}该用户！`);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "修改用户状态失败");
    } finally {
      setLoading(false);
    }
  }

  // Update user expiry time
  async function handleUpdateUserExpiry(u: AdminUser, presetValue: string) {
    if (currentUser && String(u.id) === String(currentUser.id)) {
      alert("您不能修改自己当前管理员账号的有效期。");
      return;
    }
    let expiresAt: string | null = null;
    if (presetValue !== "permanent") {
      const hours = parseInt(presetValue, 10);
      expiresAt = new Date(Date.now() + hours * 3600 * 1000).toISOString();
    }
    setLoading(true);
    try {
      await adminUpdateUserExpiry(u.id, expiresAt);
      alert("有效期更新成功！");
      loadTabData();
    } catch (err: any) {
      alert(err.message || "修改有效期失败");
    } finally {
      setLoading(false);
    }
  }

  // Update user generation limit
  async function handleUpdateUserGenerationLimit(u: AdminUser, limit: number) {
    if (u.role === "admin") {
      alert("管理员默认拥有无限次生成限额，无需修改。");
      return;
    }
    // Optimistically update local users state
    setUsers(prev =>
      prev.map(user =>
        String(user.id) === String(u.id) ? { ...user, generation_limit: limit } : user
      )
    );
    try {
      await adminUpdateUserGenerationLimit(u.id, limit);
    } catch (err: any) {
      alert(err.message || "修改生成限额失败");
      loadTabData();
    }
  }

  // Delete user
  async function handleDeleteUser(u: AdminUser) {
    if (currentUser && String(u.id) === String(currentUser.id)) {
      alert("您不能删除自己当前登录的管理员账户。");
      return;
    }
    if (!window.confirm(`确定要彻底删除用户 "${u.username}" 吗？此操作不可逆，将清除该用户的所有历史记录和设置！`)) {
      return;
    }
    setLoading(true);
    try {
      await adminDeleteUser(u.id);
      alert(`已成功删除用户 "${u.username}"！`);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "删除用户失败");
    } finally {
      setLoading(false);
    }
  }

  // Bulk delete expired users
  async function handleCleanExpiredUsers() {
    const expiredUsers = users.filter(u => {
      if (!u.expires_at) return false;
      return new Date(u.expires_at) <= new Date();
    });

    if (expiredUsers.length === 0) {
      alert("当前没有已过期的用户需要清理。");
      return;
    }

    if (!window.confirm(`确定要清理所有已过期的测试账户吗？\n当前检测到有 ${expiredUsers.length} 个已过期账户，清理操作不可逆！`)) {
      return;
    }

    setLoading(true);
    try {
      const res = await adminDeleteExpiredUsers();
      alert(`成功清理了 ${res.deleted_count} 个已过期的测试账户！`);
      loadTabData();
    } catch (err: any) {
      alert(err.message || "清理已过期用户失败");
    } finally {
      setLoading(false);
    }
  }


  return (
    <div className="page-stack" style={{ maxWidth: "1200px", margin: "0 auto", paddingBottom: "50px" }}>
      <div className="page-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <span className="section-kicker" style={{ background: "linear-gradient(135deg, var(--accent), #1ed760)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
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
        className="tabs"
        style={{
          background: "rgba(255, 255, 255, 0.03)",
          border: "1px solid var(--line)",
          padding: "4px",
          borderRadius: "var(--radius-md)",
          marginBottom: "20px"
        }}
      >
        {[
          { key: "users", label: "用户管理" },
          { key: "configs", label: "模型配置" },
          { key: "assignments", label: "配置分配" },
          { key: "statistics", label: "调用统计" },
          { key: "logs", label: "调用日志" },
          { key: "announcements", label: "公告管理" },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? "active" : ""}
            onClick={() => {
              setActiveTab(tab.key as AdminTab);
              setError(null);
            }}
            style={{
              color: activeTab === tab.key ? "var(--accent)" : "var(--muted)",
              background: activeTab === tab.key ? "rgba(255, 255, 255, 0.06)" : "transparent",
              border: "1px solid " + (activeTab === tab.key ? "var(--line-strong)" : "transparent"),
              boxShadow: activeTab === tab.key ? "var(--shadow-sm)" : "none",
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
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Temporary Account Generator Panel */}
          <Card
            title="⚡ 临时测试账号生成器"
            description="选择账号有效时间与生成数量，一键批量生成高强度的临时测试账号。账号到期后将自动停用，保障系统安全。"
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: "16px",
                alignItems: "flex-end",
                marginBottom: "20px",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "var(--muted)", fontWeight: 600 }}>有效时长</label>
                <select
                  value={genDurationHours}
                  onChange={(e) => setGenDurationHours(parseFloat(e.target.value))}
                  style={{
                    background: "rgba(255, 255, 255, 0.05)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius-sm)",
                    color: "#fff",
                    padding: "8px 12px",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  <option value={1}>1 小时</option>
                  <option value={12}>12 小时</option>
                  <option value={24}>1 天 (24 小时)</option>
                  <option value={72}>3 天 (72 小时)</option>
                  <option value={168}>7 天 (168 小时)</option>
                  <option value={720}>30 天 (720 小时)</option>
                </select>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "var(--muted)", fontWeight: 600 }}>生成数量</label>
                <select
                  value={genQuantity}
                  onChange={(e) => setGenQuantity(parseInt(e.target.value, 10))}
                  style={{
                    background: "rgba(255, 255, 255, 0.05)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius-sm)",
                    color: "#fff",
                    padding: "8px 12px",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  {[1, 2, 3, 5, 10].map((q) => (
                    <option key={q} value={q}>
                      {q} 个账号
                    </option>
                  ))}
                </select>
              </div>

              <Button
                type="button"
                variant="primary"
                onClick={handleGenerateTempAccounts}
                disabled={generating}
                style={{
                  height: "38px",
                }}
              >
                {generating ? "正在生成..." : "🚀 一键批量生成"}
              </Button>
            </div>

            {generatedAccounts.length > 0 && (
              <div
                style={{
                  background: "rgba(255, 255, 255, 0.02)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-md)",
                  padding: "16px",
                  marginTop: "16px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "12px",
                  }}
                >
                  <span style={{ fontSize: "13px", color: "var(--accent)", fontWeight: 700 }}>📋 生成结果 (请妥善保存账号凭证)：</span>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      const text = generatedAccounts
                        .map((a) => `邮箱: ${a.username}  密码: ${a.password}`)
                        .join("\n");
                      handleCopyText(text, "所有生成的测试账号凭证已复制到剪贴板！");
                    }}
                    style={{ padding: "4px 10px", fontSize: "12px" }}
                  >
                    复制全部账号
                  </Button>
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ textAlign: "left", color: "var(--muted)", borderBottom: "1px solid var(--line)" }}>
                        <th style={{ padding: "6px" }}>测试邮箱 (用户名)</th>
                        <th style={{ padding: "6px" }}>登录密码</th>
                        <th style={{ padding: "6px" }}>过期截止时间</th>
                        <th style={{ padding: "6px", textAlign: "right" }}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {generatedAccounts.map((account, idx) => (
                        <tr key={idx} style={{ borderBottom: "1px solid var(--line)" }}>
                          <td style={{ padding: "8px 6px", color: "#fff", fontWeight: 600, fontFamily: "monospace" }}>{account.username}</td>
                          <td style={{ padding: "8px 6px", color: "var(--accent)", fontWeight: 600, fontFamily: "monospace" }}>{account.password}</td>
                          <td style={{ padding: "8px 6px", color: "var(--muted)" }}>{new Date(account.expires_at).toLocaleString("zh-CN")}</td>
                          <td style={{ padding: "8px 6px", textAlign: "right" }}>
                            <Button
                              type="button"
                              variant="secondary"
                              onClick={() => {
                                handleCopyText(`邮箱: ${account.username}  密码: ${account.password}`, "账号凭证已复制！");
                              }}

                              style={{ padding: "2px 8px", fontSize: "11px" }}
                            >
                              复制
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Card>

          {/* Existing Users Table upgraded with lifecycle management */}
          <Card
            title="系统注册用户"
            description="管理系统注册的用户、角色权限、有效期截至以及整体调用明细。"
            action={
              <Button
                type="button"
                variant="danger"
                onClick={handleCleanExpiredUsers}
                style={{ padding: "6px 12px", fontSize: "12px" }}
              >
                🗑️ 清理已过期用户
              </Button>
            }
          >
            <div style={{ overflowX: "auto" }}>
              <table className="admin-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", color: "rgba(255, 255, 255, 0.85)" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.08)", textAlign: "left", color: "rgba(255, 255, 255, 0.5)" }}>
                    <th style={{ padding: "12px 8px" }}>用户</th>
                    <th style={{ padding: "12px 8px" }}>角色</th>
                    <th style={{ padding: "12px 8px" }}>生成限额</th>
                    <th style={{ padding: "12px 8px" }}>账户状态</th>
                    <th style={{ padding: "12px 8px" }}>有效期截至</th>
                    <th style={{ padding: "12px 8px" }}>备注</th>
                    <th style={{ padding: "12px 8px" }}>已分配模型</th>
                    <th style={{ padding: "12px 8px" }}>模型调用次数</th>
                    <th style={{ padding: "12px 8px" }}>注册时间</th>
                    <th style={{ padding: "12px 8px" }}>最近活动</th>
                    <th style={{ padding: "12px 8px", textAlign: "right" }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const isSelf = currentUser && String(u.id) === String(currentUser.id);
                    
                    // Expiry calculation helper
                    const formatExpiry = (expiresAt: string | null | undefined) => {
                      if (!expiresAt) return "永久有效";
                      const expDate = new Date(expiresAt);
                      const now = new Date();
                      if (expDate <= now) {
                        return "已停用/过期";
                      }
                      const diffMs = expDate.getTime() - now.getTime();
                      const diffHours = Math.ceil(diffMs / (1000 * 60 * 60));
                      if (diffHours < 24) {
                        return `剩余 ${diffHours} 小时`;
                      }
                      const diffDays = Math.ceil(diffHours / 24);
                      return `剩余 ${diffDays} 天`;
                    };

                    const isActive = u.is_active !== false;

                    return (
                      <tr key={u.id} style={{ borderBottom: "1px solid var(--line)" }}>
                        <td style={{ padding: "12px 8px", fontWeight: 600, color: "#fff" }}>
                          {!isSelf ? (
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ fontSize: "13px" }}>{u.username}</span>
                              <button
                                onClick={async () => {
                                  const newName = window.prompt(`请输入用户 "${u.username}" 的新用户名/邮箱：`, u.username);
                                  if (newName !== null && newName.trim() && newName.trim() !== u.username) {
                                    try {
                                      await adminUpdateUsername(u.id, newName.trim());
                                      alert("用户名修改成功！");
                                      loadTabData();
                                    } catch (err: any) {
                                      alert(err.message || "修改用户名失败");
                                    }
                                  }
                                }}
                                style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: "12px", padding: 0, display: "inline-flex", alignItems: "center", opacity: 0.7 }}
                                onMouseEnter={(e) => (e.currentTarget.style.opacity = "1")}
                                onMouseLeave={(e) => (e.currentTarget.style.opacity = "0.7")}
                                title="修改用户名"
                              >
                                ✏️
                              </button>
                            </div>
                          ) : (
                            <span>{u.username} <span style={{ color: "rgba(255, 255, 255, 0.3)", marginLeft: "6px", fontSize: "11px", fontWeight: "normal" }}>(当前)</span></span>
                          )}
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          <span style={{
                            background: u.role === "admin" ? "rgba(29, 185, 84, 0.15)" : "rgba(255, 255, 255, 0.06)",
                            color: u.role === "admin" ? "var(--accent)" : "rgba(255, 255, 255, 0.7)",
                            padding: "2px 8px",
                            borderRadius: "10px",
                            fontSize: "11px",
                            fontWeight: 700
                          }}>
                            {u.role === "admin" ? "管理员" : "用户"}
                          </span>
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          {u.role === "admin" ? (
                            <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: "12px" }}>无限次</span>
                          ) : (
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <input
                                type="number"
                                min="0"
                                max="999999"
                                value={u.generation_limit ?? 5}
                                onChange={async (e) => {
                                  const limitVal = parseInt(e.target.value, 10);
                                  if (!isNaN(limitVal) && limitVal >= 0) {
                                    await handleUpdateUserGenerationLimit(u, limitVal);
                                  }
                                }}
                                style={{
                                  background: "rgba(255, 255, 255, 0.05)",
                                  border: "1px solid var(--line)",
                                  borderRadius: "var(--radius-sm)",
                                  color: "#fff",
                                  fontSize: "12px",
                                  padding: "2px 6px",
                                  width: "60px",
                                  textAlign: "center"
                                }}
                              />
                              <span style={{ color: "var(--muted)", fontSize: "11px" }}>次</span>
                            </div>
                          )}
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            {isSelf ? (
                               <span style={{ color: "var(--accent)", fontSize: "12px", fontWeight: 600 }}>● 始终启用</span>
                            ) : (
                              <>
                                <span style={{
                                  fontSize: "11px",
                                  color: isActive ? "var(--accent)" : "var(--danger)",
                                  fontWeight: 600,
                                  background: isActive ? "var(--success-bg)" : "var(--danger-bg)",
                                  padding: "2px 6px",
                                  borderRadius: "4px"
                                }}>
                                  {isActive ? "已启用" : "已禁用"}
                                </span>
                                <input
                                  type="checkbox"
                                  checked={isActive}
                                  onChange={() => handleToggleUserStatus(u)}
                                  style={{
                                    cursor: "pointer",
                                    accentColor: "var(--accent)",
                                    width: "16px",
                                    height: "16px"
                                  }}
                                />
                              </>
                            )}
                          </div>
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{
                              color: !u.expires_at ? "var(--accent)" : (new Date(u.expires_at) <= new Date() ? "var(--danger)" : "var(--warning)"),
                              fontWeight: 600,
                              fontSize: "12px"
                            }}>
                              {formatExpiry(u.expires_at)}
                            </span>
                            
                            {!isSelf && (
                              <select
                                defaultValue={u.expires_at ? "custom" : "permanent"}
                                onChange={(e) => {
                                  if (e.target.value === "custom") return;
                                  handleUpdateUserExpiry(u, e.target.value);
                                }}
                                style={{
                                  background: "rgba(255, 255, 255, 0.05)",
                                  border: "1px solid var(--line)",
                                  borderRadius: "var(--radius-sm)",
                                  color: "#fff",
                                  fontSize: "11px",
                                  padding: "2px 4px",
                                  cursor: "pointer",
                                }}
                              >
                                {u.expires_at && <option value="custom">保留当前</option>}
                                <option value="24">1 天</option>
                                <option value="72">3 天</option>
                                <option value="168">7 天</option>
                                <option value="720">30 天</option>
                                <option value="permanent">永久有效</option>
                              </select>
                            )}
                          </div>
                        </td>
                        <td style={{ padding: "12px 8px", maxWidth: "150px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            {u.remark ? (
                              <span style={{ color: "rgba(255, 255, 255, 0.85)", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={u.remark}>
                                {u.remark}
                              </span>
                            ) : (
                              <span style={{ color: "rgba(255, 255, 255, 0.25)", fontSize: "12px" }}>无备注</span>
                            )}
                            <button
                              onClick={async () => {
                                const newRemark = window.prompt(`修改用户 "${u.username}" 的备注：`, u.remark || "");
                                if (newRemark !== null) {
                                  try {
                                    await adminUpdateUserRemark(u.id, newRemark.trim());
                                    loadTabData();
                                  } catch (err: any) {
                                    alert(err.message || "修改备注失败");
                                  }
                                }
                              }}
                              style={{ background: "none", border: "none", color: "rgba(255,255,255,0.4)", cursor: "pointer", fontSize: "12px", padding: 0, display: "inline-flex", alignItems: "center", opacity: 0.7 }}
                              onMouseEnter={(e) => (e.currentTarget.style.opacity = "1")}
                              onMouseLeave={(e) => (e.currentTarget.style.opacity = "0.7")}
                              title="编辑备注"
                            >
                              📝
                            </button>
                          </div>
                        </td>
                        <td style={{ padding: "12px 8px" }}>
                          {u.assigned_models && u.assigned_models.length > 0 ? (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                              {u.assigned_models.map((m, idx) => (
                                <span key={idx} style={{ background: "rgba(29, 185, 84, 0.12)", color: "var(--accent)", padding: "1px 6px", borderRadius: "4px", fontSize: "11px" }}>
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
                        <td style={{ padding: "12px 8px", textAlign: "right" }}>
                          {!isSelf && (
                            <Button
                              type="button"
                              variant="danger"
                              onClick={() => handleDeleteUser(u)}
                              style={{ padding: "4px 8px", fontSize: "11px" }}
                            >
                              删除
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {!users.length && !loading && (
                    <tr>
                      <td colSpan={11} style={{ textAlign: "center", padding: "30px", color: "rgba(255,255,255,0.4)" }}>无用户记录。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
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
                setFormProvider("custom");
                setFormModelId("");
                setFormName("");
                setFormApiKey("");
                setFormEnabled(true);
                setFormBaseUrl("");
                setFormTemp("0.7");
                setFormMaxTokens("2048");
                setFormCurl("");
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
                className="card"
                style={{
                  padding: "20px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  opacity: cfg.enabled ? 1 : 0.65
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span style={{
                      background: "var(--surface-muted)",
                      color: "var(--text)",
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "6px",
                      fontWeight: "bold",
                      textTransform: "uppercase",
                      border: "1px solid var(--line)"
                    }}>
                      {cfg.provider}
                    </span>
                    <span style={{ fontSize: "11px", color: cfg.enabled ? "var(--accent)" : "var(--danger)", fontWeight: 700 }}>
                      ● {cfg.enabled ? "已启用" : "已停用"}
                    </span>
                  </div>
                  <h4 style={{ color: "#fff", fontSize: "16px", fontWeight: "700", marginTop: "10px" }}>{cfg.name}</h4>
                  <p style={{ color: "var(--muted)", fontSize: "12px", marginTop: "2px", fontFamily: "monospace" }}>{cfg.modelId}</p>
                  
                  <div style={{ marginTop: "14px", borderTop: "1px solid var(--line)", paddingTop: "10px", display: "flex", flexDirection: "column", gap: "6px", fontSize: "12px", color: "var(--muted)" }}>
                    <div>
                      <span>已分配用户数：</span>
                      <strong style={{ color: "var(--accent)" }}>{cfg.assignment_count} 人</strong>
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
                    style={{ color: cfg.enabled ? "var(--danger)" : "var(--accent)", background: "rgba(255,255,255,0.02)" }}
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
                <tr style={{ borderBottom: "1px solid var(--line)", textAlign: "left", color: "var(--muted)" }}>
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
                  <tr key={cfg.id} style={{ borderBottom: "1px solid var(--line)" }}>
                    <td style={{ padding: "12px 8px", fontWeight: 600, color: "#fff" }}>{cfg.name}</td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{ background: "var(--surface-muted)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", border: "1px solid var(--line)" }}>{cfg.provider}</span>
                    </td>
                    <td style={{ padding: "12px 8px", fontFamily: "monospace", color: "var(--muted)" }}>{cfg.modelId}</td>
                    <td style={{ padding: "12px 8px", fontWeight: "bold", color: "var(--accent)" }}>{cfg.assignment_count} 人</td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{ color: cfg.enabled ? "var(--accent)" : "var(--danger)" }}>● {cfg.enabled ? "服务正常" : "已失效"}</span>
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
                    <td colSpan={6} style={{ textAlign: "center", padding: "30px", color: "var(--subtle)" }}>无模型配置记录。请先在“模型配置”标签中新建。</td>
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
                <option value="custom">大语言模型</option>
                <option value="doubao-multimodal">向量模型</option>
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
              <div className="card" style={{ padding: "20px" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>总调用次数</span>
                <h3 style={{ fontSize: "28px", color: "#fff", fontWeight: "800", marginTop: "6px" }}>{usageSummary.totalCalls} 次</h3>
              </div>
              <div className="card" style={{ padding: "20px" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>成功次数 / 失败率</span>
                <h3 style={{ fontSize: "28px", color: "var(--accent)", fontWeight: "800", marginTop: "6px" }}>
                  {usageSummary.successCalls} <span style={{ fontSize: "14px", color: "var(--danger)", fontWeight: "normal" }}>/ {usageSummary.totalCalls > 0 ? ((usageSummary.failedCalls / usageSummary.totalCalls) * 100).toFixed(1) : 0}% 失败</span>
                </h3>
              </div>
              <div className="card" style={{ padding: "20px" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>平均延迟时长</span>
                <h3 style={{ fontSize: "28px", color: "var(--warning)", fontWeight: "800", marginTop: "6px" }}>{(usageSummary.avgLatency / 1000).toFixed(2)} 秒</h3>
              </div>
              <div className="card" style={{ padding: "20px" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>总消费 Token 计数</span>
                <h3 style={{ fontSize: "28px", color: "#60a5fa", fontWeight: "800", marginTop: "6px" }}>{usageSummary.totalTokens.toLocaleString()}</h3>
                <span style={{ fontSize: "11px", color: "var(--muted)" }}>入 {usageSummary.totalPromptTokens.toLocaleString()} / 出 {usageSummary.totalCompletionTokens.toLocaleString()}</span>
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
                <option value="custom">大语言模型</option>
                <option value="doubao-multimodal">向量模型</option>
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

      {/* 6. Announcements Tab */}
      {activeTab === "announcements" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "14px", color: "var(--muted)" }}>
              发布全局公告，通知所有或指定用户，支持设定展示起止时间与内容自定义。
            </span>
            <Button type="button" variant="primary" onClick={handleOpenCreateAnnounce}>
              + 新增公告
            </Button>
          </div>

          <Card style={{ padding: "0", background: "rgba(255,255,255,0.01)" }}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--line-strong)", color: "rgba(255,255,255,0.5)", height: "40px" }}>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>状态</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>展示类型</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>频次设定</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>公告标题</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>公告内容</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>推送受众</th>
                    <th style={{ padding: "12px 16px", textAlign: "left" }}>有效时间段</th>
                    <th style={{ padding: "12px 16px", textAlign: "right" }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {announcements.map((ann) => {
                    const now = new Date();
                    const start = new Date(ann.start_time);
                    const end = new Date(ann.end_time);
                    let statusNode;
                    
                    if (now < start) {
                      statusNode = <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "#f59e0b", background: "rgba(245,158,11,0.1)", padding: "2px 8px", borderRadius: "10px", fontSize: "11px" }}><span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#f59e0b" }} />未开始</span>;
                    } else if (now > end) {
                      statusNode = <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "#ef4444", background: "rgba(239,68,68,0.1)", padding: "2px 8px", borderRadius: "10px", fontSize: "11px" }}><span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#ef4444" }} />已过期</span>;
                    } else {
                      statusNode = <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", color: "#10b981", background: "rgba(16,185,129,0.1)", padding: "2px 8px", borderRadius: "10px", fontSize: "11px" }}><span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#10b981" }} />进行中</span>;
                    }

                    return (
                      <tr key={ann.id} style={{ borderBottom: "1px solid var(--line)", color: "#fff", height: "55px" }}>
                        <td style={{ padding: "12px 16px" }}>{statusNode}</td>
                        <td style={{ padding: "12px 16px" }}>
                          {ann.announcement_type === "popup" ? (
                            <span style={{ color: "#f43f5e", background: "rgba(244,63,94,0.1)", border: "1px solid rgba(244,63,94,0.2)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>⚡ 中央弹出</span>
                          ) : (
                            <span style={{ color: "#10b981", background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>💊 顶部横幅</span>
                          )}
                        </td>
                        <td style={{ padding: "12px 16px" }}>
                          {ann.show_behavior === "always" ? (
                            <span style={{ color: "#1db954", background: "rgba(29,185,84,0.1)", border: "1px solid rgba(29,185,84,0.2)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>📌 一直显示</span>
                          ) : ann.show_behavior === "every_login" ? (
                            <span style={{ color: "#f59e0b", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>🔄 每次登录</span>
                          ) : (
                            <span style={{ color: "#38bdf8", background: "rgba(56,189,248,0.1)", border: "1px solid rgba(56,189,248,0.2)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>💊 仅展示一次</span>
                          )}
                        </td>
                        <td style={{ padding: "12px 16px", fontWeight: "bold" }}>{ann.title}</td>
                        <td style={{ padding: "12px 16px", maxWidth: "250px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "rgba(255,255,255,0.7)" }}>
                          {ann.content}
                        </td>
                        <td style={{ padding: "12px 16px" }}>
                          {ann.target_type === "all" ? (
                            <span style={{ color: "#38bdf8", background: "rgba(56,189,248,0.1)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px" }}>全体用户</span>
                          ) : (
                            <span style={{ color: "#c084fc", background: "rgba(192,132,252,0.1)", padding: "2px 6px", borderRadius: "4px", fontSize: "11px" }} title={ann.target_users}>
                              指定用户 ({ann.target_users?.split(",").length || 0})
                            </span>
                          )}
                        </td>
                        <td style={{ padding: "12px 16px", fontSize: "11px", color: "rgba(255,255,255,0.5)", fontFamily: "monospace" }}>
                          {new Date(ann.start_time).toLocaleString()} <br />
                          至 {new Date(ann.end_time).toLocaleString()}
                        </td>
                        <td style={{ padding: "12px 16px", textAlign: "right" }}>
                          <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                            <Button type="button" variant="secondary" onClick={() => handleOpenEditAnnounce(ann)} style={{ padding: "4px 8px", fontSize: "12px" }}>
                              编辑
                            </Button>
                            <button
                              type="button"
                              onClick={() => ann.id && handleDeleteAnnouncement(ann.id)}
                              style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#f87171", cursor: "pointer", fontSize: "12px", borderRadius: "4px", padding: "4px 8px" }}
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {!announcements.length && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: "center", padding: "30px", color: "rgba(255,255,255,0.3)" }}>暂无公告，点击右上角发布新公告。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {/* --- MODAL DIALOGS --- */}

      {/* Create / Edit Announcement Modal */}
      {showAnnounceModal && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", justifyContent: "center", alignItems: "flex-start", overflowY: "auto", padding: "40px 16px", zIndex: 1000 }}>
          <form onSubmit={handleSaveAnnouncement} style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "500px", maxWidth: "100%", display: "flex", flexDirection: "column", gap: "16px", marginBottom: "40px" }}>
            <h3 style={{ color: "#fff", fontSize: "18px", fontWeight: "800" }}>{editingAnnouncement ? "编辑全局公告" : "发布新全局公告"}</h3>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>公告标题 *</label>
              <input
                type="text"
                required
                value={annTitle}
                placeholder="如: 系统升级维护通知"
                onChange={(e) => setAnnTitle(e.target.value)}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>公告内容 *</label>
              <textarea
                required
                value={annContent}
                placeholder="在此输入公告正文内容，支持换行..."
                onChange={(e) => setAnnContent(e.target.value)}
                rows={6}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px", resize: "vertical" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>开始展示时间 *</label>
                <input
                  type="datetime-local"
                  required
                  value={annStartTime}
                  onChange={(e) => setAnnStartTime(e.target.value)}
                  style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>结束展示时间 *</label>
                <input
                  type="datetime-local"
                  required
                  value={annEndTime}
                  onChange={(e) => setAnnEndTime(e.target.value)}
                  style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
                />
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>公告展示方式 *</label>
              <div style={{ display: "flex", gap: "16px" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="annType"
                    checked={annType === "top"}
                    onChange={() => setAnnType("top")}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  顶部横幅 (Top banner)
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="annType"
                    checked={annType === "popup"}
                    onChange={() => {
                      setAnnType("popup");
                      if (annShowBehavior === "always") {
                        setAnnShowBehavior("once");
                      }
                    }}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  中央弹出 (Popup alert)
                </label>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>弹出频次设定 *</label>
              <div style={{ display: "flex", gap: "16px" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="showBehavior"
                    checked={annShowBehavior === "once"}
                    onChange={() => setAnnShowBehavior("once")}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  仅展示一次 (Once)
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="showBehavior"
                    checked={annShowBehavior === "every_login"}
                    onChange={() => setAnnShowBehavior("every_login")}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  每次登录都展示 (Every login)
                </label>
                {annType === "top" && (
                  <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="showBehavior"
                      checked={annShowBehavior === "always"}
                      onChange={() => setAnnShowBehavior("always")}
                      style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                    />
                    一直显示 (Always)
                  </label>
                )}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>推送范围 *</label>
              <div style={{ display: "flex", gap: "16px" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={annTargetType === "all"}
                    onChange={() => setAnnTargetType("all")}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  全部用户
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "#fff", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={annTargetType === "specific"}
                    onChange={() => setAnnTargetType("specific")}
                    style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                  />
                  指定用户
                </label>
              </div>
            </div>

            {annTargetType === "specific" && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px", background: "rgba(255, 255, 255, 0.02)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: "var(--radius-md)", padding: "16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label style={{ fontSize: "13px", fontWeight: "bold", color: "#fff" }}>指定受众勾选管理 *</label>
                  <span style={{ fontSize: "11px", color: "var(--accent)", fontWeight: "bold", background: "rgba(56,189,248,0.1)", padding: "2px 8px", borderRadius: "10px" }}>
                    已勾选: {selectedUsernames.length} 人
                  </span>
                </div>
                
                {selectedUsernames.length > 0 && (
                  <div style={{ fontSize: "11px", color: "rgba(255,255,255,0.4)", maxHeight: "40px", overflowY: "auto", background: "rgba(0,0,0,0.2)", padding: "6px 10px", borderRadius: "4px", border: "1px dashed rgba(255,255,255,0.1)", wordBreak: "break-all" }}>
                    <strong>受众名单:</strong> {selectedUsernames.join(", ")}
                  </div>
                )}

                {/* Filters Row */}
                <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr", gap: "8px" }}>
                  <input
                    type="text"
                    placeholder="🔍 搜索用户名..."
                    value={userSearchQuery}
                    onChange={(e) => setUserSearchQuery(e.target.value)}
                    style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.12)", borderRadius: "4px", color: "#fff", padding: "6px 10px", fontSize: "12px", width: "100%", boxSizing: "border-box" }}
                  />
                  <select
                    value={userTypeFilter}
                    onChange={(e) => setUserTypeFilter(e.target.value as any)}
                    style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.12)", borderRadius: "4px", color: "#fff", padding: "6px 10px", fontSize: "12px" }}
                  >
                    <option value="all">所有账号</option>
                    <option value="temp">临时用户</option>
                    <option value="permanent">永久用户</option>
                  </select>
                  <select
                    value={userTimeFilter}
                    onChange={(e) => setUserTimeFilter(e.target.value as any)}
                    style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.12)", borderRadius: "4px", color: "#fff", padding: "6px 10px", fontSize: "12px" }}
                  >
                    <option value="all">所有注册时间</option>
                    <option value="today">今天注册</option>
                    <option value="3days">最近3天</option>
                    <option value="7days">最近7天</option>
                    <option value="30days">最近30天</option>
                  </select>
                </div>

                {/* Selection helper buttons */}
                <div style={{ display: "flex", gap: "8px", fontSize: "11px" }}>
                  <button
                    type="button"
                    onClick={handleToggleSelectAllFiltered}
                    style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "4px", color: "#fff", padding: "4px 8px", cursor: "pointer" }}
                  >
                    {filteredUsersForTarget.every(name => selectedUsernames.includes(name.username)) ? "取消全选当前" : "全选当前过滤"}
                  </button>
                  <button
                    type="button"
                    onClick={handleClearAllSelections}
                    style={{ background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.2)", borderRadius: "4px", color: "#f87171", padding: "4px 8px", cursor: "pointer" }}
                  >
                    清空选择
                  </button>
                  <span style={{ marginLeft: "auto", color: "rgba(255,255,255,0.4)", display: "flex", alignItems: "center" }}>
                    过滤出: {filteredUsersForTarget.length} 人
                  </span>
                </div>

                {/* Scrollable Checklist */}
                <div style={{ maxHeight: "160px", overflowY: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "4px", background: "rgba(0,0,0,0.15)", padding: "4px" }}>
                  {filteredUsersForTarget.map((u) => {
                    const isSelected = selectedUsernames.includes(u.username);
                    const regDate = new Date(u.created_at).toLocaleDateString("zh-CN");
                    return (
                      <div 
                        key={u.id} 
                        style={{ 
                          display: "flex", 
                          alignItems: "center", 
                          gap: "8px", 
                          padding: "6px 8px", 
                          borderRadius: "3px", 
                          background: isSelected ? "rgba(56, 189, 248, 0.05)" : "transparent",
                          borderBottom: "1px solid rgba(255,255,255,0.02)" 
                        }}
                      >
                        <input
                          type="checkbox"
                          id={`select-user-${u.id}`}
                          checked={isSelected}
                          onChange={() => {
                            if (isSelected) {
                              setSelectedUsernames(prev => prev.filter(name => name !== u.username));
                            } else {
                              setSelectedUsernames(prev => [...prev, u.username]);
                            }
                          }}
                          style={{ width: "14px", height: "14px", cursor: "pointer", accentColor: "var(--accent)" }}
                        />
                        <label 
                          htmlFor={`select-user-${u.id}`} 
                          style={{ 
                            fontSize: "12px", 
                            color: isSelected ? "#fff" : "rgba(255,255,255,0.85)", 
                            fontWeight: isSelected ? "bold" : "normal",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            flex: 1
                          }}
                        >
                          <span>{u.username}</span>
                          {u.expires_at ? (
                            <span style={{ color: "#f87171", background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.15)", borderRadius: "3px", padding: "1px 4px", fontSize: "9px" }}>临时</span>
                          ) : (
                            <span style={{ color: "#34d399", background: "rgba(52,211,153,0.1)", border: "1px solid rgba(52,211,153,0.15)", borderRadius: "3px", padding: "1px 4px", fontSize: "9px" }}>永久</span>
                          )}
                          <span style={{ marginLeft: "auto", fontSize: "10px", color: "rgba(255,255,255,0.3)" }}>注册: {regDate}</span>
                        </label>
                      </div>
                    );
                  })}
                  {!filteredUsersForTarget.length && (
                    <div style={{ padding: "20px", textAlign: "center", color: "rgba(255,255,255,0.3)", fontSize: "12px" }}>
                      没有符合当前过滤条件的用户。
                    </div>
                  )}
                </div>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "10px" }}>
              <Button type="button" variant="secondary" onClick={() => setShowAnnounceModal(false)}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={loading}>
                {loading ? "正在保存..." : "确认发布"}
              </Button>
            </div>
          </form>
        </div>
      )}

      {/* Create / Edit Config Modal */}
      {showConfigModal && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", justifyContent: "center", alignItems: "flex-start", overflowY: "auto", padding: "40px 16px", zIndex: 1000 }}>
          <form onSubmit={handleSaveConfig} style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "450px", maxWidth: "100%", display: "flex", flexDirection: "column", gap: "16px", marginBottom: "40px" }}>
            <h3 style={{ color: "#fff", fontSize: "18px", fontWeight: "800" }}>{isEditMode ? "编辑管理员托管配置" : "新建管理员托管配置"}</h3>
            <p style={{ fontSize: "12px", color: "rgba(255,255,255,0.5)" }}>
              该配置的所有权属于管理员/系统本身，普通用户无法查看真实的 API 密钥。
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>从 cURL 导入 (一键解析并自动填表，可选)</label>
              <textarea
                value={formCurl}
                placeholder="在此粘贴 cURL 命令行，如：&#10;curl https://api.deepseek.com/v1/chat/completions -H 'Authorization: Bearer sk-...' -d '{&quot;model&quot;: &quot;deepseek-chat&quot;}'"
                onChange={(e) => {
                  setFormCurl(e.target.value);
                  handleImportFromCurl(e.target.value);
                }}
                rows={3}
                style={{
                  background: "#1e1e1e",
                  border: "1px solid rgba(255,255,255,0.15)",
                  borderRadius: "var(--radius-md)",
                  color: "#fff",
                  padding: "8px 12px",
                  fontSize: "12px",
                  fontFamily: "monospace",
                  resize: "vertical"
                }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>提供商 (Provider) *</label>
              <select
                value={formProvider}
                onChange={(e) => {
                  setFormProvider(e.target.value);
                  if (e.target.value === "custom") setFormModelId("");
                  else if (e.target.value === "doubao-multimodal") setFormModelId("");
                  else setFormModelId("");
                }}
                style={{ background: "#1e1e1e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "var(--radius-md)", color: "#fff", padding: "8px 12px", fontSize: "13px" }}
              >
                <option value="custom">大语言模型 (Chat/LLM)</option>
                <option value="doubao-multimodal">向量模型 (Embedding)</option>
              </select>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>配置名称 (DisplayName) *</label>
              <input
                type="text"
                required
                value={formName}
                placeholder="如: 我的自定义模型"
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
                placeholder="如: gpt-4o-mini 或你的模型 ID"
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

            {(formProvider === "custom" || formProvider === "doubao-multimodal") && (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", color: "rgba(255,255,255,0.7)" }}>接口地址 (Base URL) *</label>
                <input
                  type="text"
                  required
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
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)", display: "flex", justifyContent: "center", alignItems: "flex-start", overflowY: "auto", padding: "40px 16px", zIndex: 1000 }}>
          <div style={{ background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "var(--radius-lg)", padding: "24px", width: "500px", maxWidth: "100%", display: "flex", flexDirection: "column", gap: "16px", marginBottom: "40px" }}>
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
                        style={{
                          width: "16px",
                          height: "16px",
                          minHeight: "auto",
                          padding: 0,
                          margin: 0,
                          cursor: "pointer",
                          accentColor: "var(--accent)"
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

            <div style={{ fontSize: "11px", color: "var(--warning)", background: "var(--warning-bg)", border: "1px solid var(--warning-border)", borderRadius: "6px", padding: "8px", lineHeight: "1.4" }}>
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
