import { useState, useEffect, useRef } from "react";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { StarLoadingAnimation } from "../components/StarLoadingAnimation";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { apiFetch } from "../services/apiClient";

gsap.registerPlugin(useGSAP);

interface StarStoryRecord {
  id: string;
  title: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  full_text: string;
  style: string;
  created_at: string;
  updated_at: string;
}

interface ResumeAdvice {
  id: string;
  priority: "high" | "medium" | "low";
  issue: string;
  suggestion: string;
  example: string;
  impact: string;
  basedOnChunkIds?: string[];
}

interface JdHistoryItem {
  id: string;
  input_json?: {
    company?: string;
    title?: string;
    jdText?: string;
  };
  result_json?: {
    draft?: {
      company?: string;
      title?: string;
      jdText?: string;
    };
  };
  resumeAdvice?: ResumeAdvice[];
}

export function StarPage({
  preselectedContext,
  onClearPreselectedContext,
  onGenerationUsed
}: {
  preselectedContext?: { jdId: string; adviceId: string } | null;
  onClearPreselectedContext?: () => void;
  onGenerationUsed?: () => void;
}) {
  const pageRef = useRef<HTMLDivElement | null>(null);

  // Modes: list, wizard, polish
  const [mode, setMode] = useState<"list" | "wizard" | "polish">("list");
  const [stories, setStories] = useState<StarStoryRecord[]>([]);
  const [historyJds, setHistoryJds] = useState<JdHistoryItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

  // Available Model Configs
  const [modelConfigs, setModelConfigs] = useState<any[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState<string>("");

  // Form States
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [situation, setSituation] = useState("");
  const [task, setTask] = useState("");
  const [action, setAction] = useState("");
  const [result, setResult] = useState("");
  const [selectedJdText, setSelectedJdText] = useState("");
  const [selectedJdId, setSelectedJdId] = useState("");

  // Selected JD Resume Advice (Import list)
  const [selectedJdAdvice, setSelectedJdAdvice] = useState<ResumeAdvice[]>([]);

  // AI & Polish states
  const [activeStep, setActiveStep] = useState(0);
  const [aiSuggestion, setAiSuggestion] = useState("");
  const [loadingSuggestion, setLoadingSuggestion] = useState(false);
  const [polishedText, setPolishedText] = useState("");
  const [loadingPolish, setLoadingPolish] = useState(false);
  const [activeStyle, setActiveStyle] = useState("standard");

  // Smart Rewrite states
  const [smartRewriteOpen, setSmartRewriteOpen] = useState(true);
  const [smartRewriteText, setSmartRewriteText] = useState("");
  const [loadingSmartRewrite, setLoadingSmartRewrite] = useState(false);

  const steps = [
    { key: "situation", label: "S - 背景 (Situation)", placeholder: "当时面临什么业务场景、技术痛点、性能瓶颈或产品重构需求？" },
    { key: "task", label: "T - 任务 (Task)", placeholder: "你需要完成什么量化技术目标？（如首屏加载从 3s 降到 1.5s，或处理万级并发）" },
    { key: "action", label: "A - 行动 (Action)", placeholder: "你采用了什么技术栈、架构方案或算法？具体怎么重构和调试并实现它的？" },
    { key: "result", label: "R - 结果 (Result)", placeholder: "最终的技术与业务指标如何？有什么量化提升？（如性能提升 50%，QPS 翻倍）" },
  ];

  // Fetch Saved Stories
  const fetchStories = async () => {
    try {
      const data = await apiFetch<{ stories: StarStoryRecord[] }>("/api/star/stories");
      setStories(data.stories || []);
    } catch (e) {
      console.error("加载故事列表失败:", e);
    }
  };

  // Fetch JD records from history
  const fetchHistoryJds = async () => {
    try {
      const data = await apiFetch<{ records: any[] }>("/api/history?limit=30");
      const parsedRecords = (data.records || []).map((r) => {
        let resultObj = r;
        if (r.result_json) {
          if (typeof r.result_json === "string") {
            try { resultObj = JSON.parse(r.result_json); } catch { resultObj = r; }
          } else if (typeof r.result_json === "object") {
            resultObj = r.result_json;
          }
        }
        return {
          ...resultObj,
          id: r.id,
          status: r.status,
          resumeAdvice: resultObj?.resumeAdvice || [],
        };
      });
      setHistoryJds(parsedRecords);
    } catch (e) {
      console.error("加载岗位历史失败:", e);
    }
  };

  // Fetch Model Configs
  const fetchConfigs = async () => {
    try {
      const data = await apiFetch<{ configs: any[] }>("/api/configs");
      const list = data.configs || [];
      setModelConfigs(list);
      // Default to first enabled config
      const enabled = list.filter(c => c.enabled);
      if (enabled.length > 0) {
        setSelectedConfigId(enabled[0].id);
      }
    } catch (e) {
      console.error("加载模型配置失败:", e);
    }
  };

  useEffect(() => {
    fetchStories();
    fetchHistoryJds();
    fetchConfigs();
  }, []);

  // Automatically pre-fill the smart rewrite content when redirected with a selected advice from history
  useEffect(() => {
    if (preselectedContext && preselectedContext.jdId && historyJds.length > 0) {
      setSelectedJdId(preselectedContext.jdId);
      const item = historyJds.find((x) => x.id === preselectedContext.jdId);
      if (item) {
        const jdText = item.input_json?.jdText || item.result_json?.draft?.jdText || "";
        setSelectedJdText(jdText);
        const adviceList = item.resumeAdvice || [];
        setSelectedJdAdvice(adviceList);
        
        // Find the specific advice item
        const adv = adviceList.find((a) => a.id === preselectedContext.adviceId);
        if (adv) {
          const chunks = (item as any).parsedResume?.chunks || (item as any).retrievedResumeChunks || [];
          const basedOn = adv.basedOnChunkIds || [];
          const matched = chunks.filter((c: any) => basedOn.includes(c.id));
          const originalText = matched.length > 0
            ? matched.map((c: any) => c.content || c.text || "").join("\n").trim()
            : "";
          
          if (originalText) {
            const targetText = `${originalText}\n\n【修改目标】：针对以下简历问题进行针对性智能改写：\n- 问题缺陷：${adv.issue}\n- 优化建议：${adv.suggestion}`;
            setSmartRewriteText(targetText);
          }
        }
      }
      
      setSmartRewriteOpen(true);
      setMode("wizard");
      
      onClearPreselectedContext?.();
    }
  }, [preselectedContext, historyJds]);

  // GSAP animations for page modes
  useGSAP(() => {
    gsap.fromTo(".star-fade-in", 
      { opacity: 0, y: 15 },
      { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }
    );
  }, { dependencies: [mode], scope: pageRef });

  // GSAP for wizard steps
  useGSAP(() => {
    gsap.fromTo(".wizard-content-box", 
      { opacity: 0, x: 20 },
      { opacity: 1, x: 0, duration: 0.4, ease: "power2.out" }
    );
  }, { dependencies: [activeStep], scope: pageRef });

  const getStepValue = (key: string) => {
    if (key === "situation") return situation;
    if (key === "task") return task;
    if (key === "action") return action;
    return result;
  };

  const setStepValue = (key: string, val: string) => {
    if (key === "situation") setSituation(val);
    else if (key === "task") setTask(val);
    else if (key === "action") setAction(val);
    else setResult(val);
  };

  const handleJdSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSelectedJdId(id);
    if (!id) {
      setSelectedJdText("");
      setSelectedJdAdvice([]);
      return;
    }
    const item = historyJds.find((x) => x.id === id);
    const jdText = item?.input_json?.jdText || item?.result_json?.draft?.jdText || "";
    setSelectedJdText(jdText);
    setSelectedJdAdvice(item?.resumeAdvice || []);
  };

  const handleFillAdvice = (text: string) => {
    if (!text) return;
    const currentKey = steps[activeStep].key;
    const currentVal = getStepValue(currentKey);
    if (currentVal.trim()) {
      setStepValue(currentKey, `${currentVal}\n\n${text}`);
    } else {
      setStepValue(currentKey, text);
    }
  };

  const getOriginalResumeText = (adviceItem: ResumeAdvice) => {
    const currentJdItem = historyJds.find((h) => h.id === selectedJdId);
    if (!currentJdItem) return "";

    const chunks = (currentJdItem as any).parsedResume?.chunks || (currentJdItem as any).retrievedResumeChunks || [];
    const basedOn = adviceItem.basedOnChunkIds || [];

    if (!chunks.length || !basedOn.length) return "";

    const matched = chunks.filter((c: any) => basedOn.includes(c.id));
    if (matched.length > 0) {
      return matched.map((c: any) => c.content || c.text || "").join("\n").trim();
    }
    return "";
  };

  const handleImportAdviceToStar = (text: string, label = "优化改写示例") => {
    if (!text) return;
    
    // Parse S/T/A/R sections using regex
    const sMatch = text.match(/(?:S|背景|Situation)\s*[:：]\s*([\s\S]*?)(?=(?:T|任务|Task|A|行动|Action|R|结果|Result|$))/i);
    const tMatch = text.match(/(?:T|任务|Task)\s*[:：]\s*([\s\S]*?)(?=(?:S|背景|Situation|A|行动|Action|R|结果|Result|$))/i);
    const aMatch = text.match(/(?:A|行动|Action)\s*[:：]\s*([\s\S]*?)(?=(?:S|背景|Situation|T|任务|Task|R|结果|Result|$))/i);
    const rMatch = text.match(/(?:R|结果|Result)\s*[:：]\s*([\s\S]*?)(?=(?:S|背景|Situation|T|任务|Task|A|行动|Action|$))/i);
    
    let parsedS = sMatch ? sMatch[1].trim() : "";
    let parsedT = tMatch ? tMatch[1].trim() : "";
    let parsedA = aMatch ? aMatch[1].trim() : "";
    let parsedR = rMatch ? rMatch[1].trim() : "";
    
    // Heuristic fallback if no markers are matched
    if (!parsedS && !parsedT && !parsedA && !parsedR) {
      const cleanText = text.replace(/[\*\-#`]/g, "").trim();
      const parts = cleanText.split(/[。；\n\r]/).map(s => s.trim()).filter(Boolean);
      if (parts.length >= 4) {
        parsedS = parts[0];
        parsedT = parts[1];
        parsedA = parts.slice(2, parts.length - 1).join("。");
        parsedR = parts[parts.length - 1];
      } else if (parts.length === 3) {
        parsedS = parts[0];
        parsedT = parts[1];
        parsedA = parts[2];
        parsedR = "";
      } else if (parts.length === 2) {
        parsedS = parts[0];
        parsedT = "";
        parsedA = parts[1];
        parsedR = "";
      } else {
        parsedS = cleanText;
      }
    }
    
    if (parsedS) setSituation(parsedS);
    if (parsedT) setTask(parsedT);
    if (parsedA) setAction(parsedA);
    if (parsedR) setResult(parsedR);
    
    alert(`已成功将【${label}】一键智能分配并填入 S-T-A-R 各个字段中，你可以在后续步骤中继续精修！`);
  };

  // Smart Rewrite: send entire project experience to LLM
  const handleSmartRewrite = async () => {
    if (!smartRewriteText.trim() || smartRewriteText.trim().length < 10) {
      alert("请输入至少 10 个字符的项目经历描述。");
      return;
    }
    setLoadingSmartRewrite(true);
    try {
      const data = await apiFetch<{
        situation?: string;
        task?: string;
        action?: string;
        result?: string;
        polishedText?: string;
      }>("/api/star/smart-rewrite", {
        method: "POST",
        body: JSON.stringify({
          original_text: smartRewriteText,
          style: activeStyle,
          jd_text: selectedJdText || null,
          config_id: selectedConfigId || null,
        }),
      });
      // Fill S/T/A/R fields
      if (data.situation) setSituation(data.situation);
      if (data.task) setTask(data.task);
      if (data.action) setAction(data.action);
      if (data.result) setResult(data.result);
      if (data.polishedText) setPolishedText(data.polishedText);
      onGenerationUsed?.();
      // Auto-jump to polish mode to show results
      setMode("polish");
      setSmartRewriteOpen(false);
    } catch (e: any) {
      alert(e.message || "智能改写失败，请检查网络与模型配置。");
    } finally {
      setLoadingSmartRewrite(false);
    }
  };

  // Generate AI Suggestion for the active segment
  const handleGenerateSuggestion = async () => {
    const currentKey = steps[activeStep].key;
    const currentVal = getStepValue(currentKey);
    setLoadingSuggestion(true);
    setAiSuggestion("");

    try {
      const data = await apiFetch<{ suggestion?: string }>("/api/star/generate-segment", {
        method: "POST",
        body: JSON.stringify({
          segment_type: currentKey.toUpperCase(),
          input_text: currentVal,
          jd_text: selectedJdText || null,
          current_star: { situation, task, action, result },
          config_id: selectedConfigId || null,
        }),
      });
      setAiSuggestion(data.suggestion || "AI 未能产出合理建议。");
    } catch (e) {
      setAiSuggestion("建议生成出错，请确认网络连接与模型配置。");
    } finally {
      setLoadingSuggestion(false);
    }
  };

  // Polish whole story into one markdown paragraph
  const handlePolishStory = async () => {
    setLoadingPolish(true);
    setPolishedText("");
    try {
      const data = await apiFetch<{ polishedText?: string }>("/api/star/polish", {
        method: "POST",
        body: JSON.stringify({
          situation,
          task,
          action,
          result,
          style: activeStyle,
          jd_text: selectedJdText || null,
          config_id: selectedConfigId || null,
        }),
      });
      setPolishedText(data.polishedText || "");
      onGenerationUsed?.();
    } catch (e: any) {
      setPolishedText("智能打磨失败，请检查你的剩余生成次数以及模型配置。");
      alert(e.message || "打磨失败，额度可能已耗尽。");
    } finally {
      setLoadingPolish(false);
    }
  };

  // Save/Create project story
  const handleSaveStory = async () => {
    if (!title.trim()) {
      alert("请输入项目故事名称。");
      return;
    }
    const payload = {
      title,
      situation,
      task,
      action,
      result,
      full_text: polishedText,
      style: activeStyle,
    };
    try {
      const url = editingId ? `/api/star/stories/${editingId}` : "/api/star/stories";
      const method = editingId ? "PUT" : "POST";
      await apiFetch(url, {
        method,
        body: JSON.stringify(payload),
      });
      setMode("list");
      fetchStories();
      alert("项目故事已成功保存！");
    } catch (e) {
      alert("保存失败，请检查数据。");
    }
  };

  const handleStartNew = () => {
    setEditingId(null);
    setTitle("");
    setSituation("");
    setTask("");
    setAction("");
    setResult("");
    setSelectedJdId("");
    setSelectedJdText("");
    setSelectedJdAdvice([]);
    setActiveStep(0);
    setAiSuggestion("");
    setPolishedText("");
    setSmartRewriteText("");
    setSmartRewriteOpen(true);
    setMode("wizard");
  };

  const handleEdit = (story: StarStoryRecord) => {
    setEditingId(story.id);
    setTitle(story.title);
    setSituation(story.situation);
    setTask(story.task);
    setAction(story.action);
    setResult(story.result);
    setPolishedText(story.full_text);
    setActiveStyle(story.style || "standard");
    setSelectedJdId("");
    setSelectedJdText("");
    setSelectedJdAdvice([]);
    setActiveStep(0);
    setAiSuggestion("");
    setMode("wizard");
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("确定要删除这个项目故事吗？")) return;
    try {
      await apiFetch(`/api/star/stories/${id}`, { method: "DELETE" });
      fetchStories();
    } catch (e) {
      alert("删除失败");
    }
  };

  const handleClone = async (story: StarStoryRecord) => {
    const payload = {
      title: `${story.title} (副本)`,
      situation: story.situation,
      task: story.task,
      action: story.action,
      result: story.result,
      full_text: story.full_text,
      style: story.style,
    };
    try {
      await apiFetch("/api/star/stories", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      fetchStories();
    } catch (e) {
      console.error(e);
    }
  };

  const filteredStories = stories.filter((x) =>
    (x.title || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (x.full_text || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getStyleBadgeTone = (s: string): "neutral" | "success" | "warning" | "danger" | "info" => {
    if (s === "big-tech") return "info";
    if (s === "start-up") return "success";
    return "neutral";
  };

  const getStyleLabel = (s: string) => {
    if (s === "big-tech") return "大厂硬核风";
    if (s === "start-up") return "敏捷突击风";
    return "通用标准风";
  };

  // Convert markdown simple bullet points to HTML
  const renderPolishedMarkdown = (text: string) => {
    if (!text) return <p className="muted">打磨后的内容将在这里以排版优雅的简历格式实时显示。</p>;
    const lines = text.split("\n");
    return (
      <div className="polished-preview-content">
        {lines.map((line, idx) => {
          let trimmed = line.trim();
          if (trimmed.startsWith("###")) {
            return <h4 key={idx} style={{ marginTop: "14px", marginBottom: "6px", color: "var(--accent)", fontSize: "14px", fontWeight: "700" }}>{trimmed.replace(/^###\s*/, "")}</h4>;
          }
          if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
            return <p key={idx} style={{ fontWeight: 700, color: "var(--text)", marginBottom: "6px" }}>{trimmed.replace(/\*\*/g, "")}</p>;
          }
          if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
            let boldParsed = trimmed.replace(/^[-*]\s*/, "");
            const parts = boldParsed.split("**");
            return (
              <li key={idx} style={{ marginLeft: "14px", listStyleType: "disc", marginBottom: "6px", color: "var(--text)" }}>
                {parts.map((p, i) => i % 2 === 1 ? <strong key={i} style={{ color: "var(--accent)", fontWeight: "700" }}>{p}</strong> : p)}
              </li>
            );
          }
          if (!trimmed) return <div key={idx} style={{ height: "8px" }} />;
          const parts = trimmed.split("**");
          return (
            <p key={idx} style={{ marginBottom: "6px", lineHeight: "1.6", color: "var(--text)" }}>
              {parts.map((p, i) => i % 2 === 1 ? <strong key={i} style={{ color: "var(--accent)", fontWeight: "700" }}>{p}</strong> : p)}
            </p>
          );
        })}
      </div>
    );
  };

  return (
    <div ref={pageRef} className="page-stack star-page" style={{ paddingBottom: "40px" }}>
      
      {/* Scope specific UI Overrides to maintain consistent light caramel sand theme */}
      <style>{`
        .wizard-step-bar {
          display: flex;
          justify-content: space-between;
          position: relative;
          margin-bottom: 28px;
          padding: 0 10px;
        }
        .wizard-step-bar::after {
          content: '';
          position: absolute;
          top: 14px;
          left: 6%;
          right: 6%;
          height: 2px;
          background: var(--line);
          z-index: 1;
        }
        .wizard-step-indicator {
          z-index: 2;
          display: flex;
          flex-direction: column;
          align-items: center;
          cursor: pointer;
        }
        .wizard-circle {
          width: 30px;
          height: 30px;
          border-radius: 50%;
          background: var(--surface-muted);
          border: 2px solid var(--line-strong);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          font-weight: 700;
          color: var(--muted);
          transition: all 200ms ease;
        }
        .wizard-step-indicator.active .wizard-circle {
          background: var(--accent);
          border-color: var(--accent);
          color: var(--surface);
          box-shadow: 0 0 8px rgba(180, 83, 9, 0.25);
        }
        .wizard-step-indicator.completed .wizard-circle {
          background: var(--accent-bg);
          border-color: var(--accent);
          color: var(--accent);
        }
        .wizard-step-label {
          font-size: 11px;
          margin-top: 6px;
          color: var(--subtle);
          font-weight: 600;
        }
        .wizard-step-indicator.active .wizard-step-label {
          color: var(--accent);
          font-weight: 700;
        }
        .wizard-layout {
          display: grid;
          grid-template-columns: 1.2fr 1fr;
          gap: 24px;
        }
        .polish-layout {
          display: grid;
          grid-template-columns: 1fr 1.2fr;
          gap: 24px;
        }
        @media (max-width: 768px) {
          .wizard-layout, .polish-layout {
            grid-template-columns: 1fr;
          }
        }
        .suggestion-box {
          background: var(--surface-muted);
          border: 1px dashed var(--line-strong);
          border-radius: var(--radius);
          padding: 16px;
          max-height: 480px;
          overflow-y: auto;
          font-size: 13px;
          line-height: 1.6;
          color: var(--text);
        }
        .polished-workspace-box {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: var(--radius);
          padding: 24px;
          min-height: 480px;
          display: flex;
          flex-direction: column;
          box-shadow: var(--shadow-md);
        }
        .polished-preview-content {
          font-family: inherit;
          line-height: 1.7;
          color: var(--text);
          font-size: 13px;
        }
        .style-btn {
          padding: 8px 16px;
          border-radius: 20px;
          border: 1px solid var(--line-strong);
          background: var(--surface);
          color: var(--muted);
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: all 150ms ease;
        }
        .style-btn:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
        .style-btn.active {
          background: var(--accent-bg);
          border-color: var(--accent);
          color: var(--accent);
        }
        .card-grid-custom {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }
        .story-list-card {
          position: relative;
          min-height: 220px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          background: var(--surface);
          border: 1px solid var(--line);
        }
        .dashboard-header-custom {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
        }
        .dashboard-search {
          padding: 8px 16px;
          background: var(--surface);
          border: 1px solid var(--line-strong);
          border-radius: 20px;
          color: var(--text);
          font-size: 13px;
          width: 240px;
          outline: none;
        }
        .dashboard-search:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(180, 83, 9, 0.08);
        }
        .advice-import-panel {
          background: var(--surface-muted);
          border: 1px solid var(--line);
          border-radius: var(--radius);
          padding: 16px;
          max-height: 480px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .advice-item-card {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: var(--radius-sm);
          padding: 12px;
          font-size: 12.5px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          box-shadow: var(--shadow-sm);
        }
        .smart-rewrite-panel {
          background: linear-gradient(135deg, var(--surface) 0%, var(--accent-bg) 100%);
          border: 1.5px solid var(--accent);
          border-radius: var(--radius);
          padding: 0;
          margin-bottom: 20px;
          overflow: hidden;
          transition: box-shadow 0.3s ease;
        }
        .smart-rewrite-panel:hover {
          box-shadow: 0 4px 20px rgba(180, 83, 9, 0.1);
        }
        .smart-rewrite-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 14px 18px;
          cursor: pointer;
          user-select: none;
        }
        .smart-rewrite-header:hover {
          background: rgba(180, 83, 9, 0.04);
        }
        .smart-rewrite-header h4 {
          margin: 0;
          font-size: 14px;
          font-weight: 700;
          color: var(--accent);
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .smart-rewrite-body {
          padding: 0 18px 18px 18px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .smart-rewrite-body textarea {
          width: 100%;
          min-height: 140px;
          resize: vertical;
          border-radius: var(--radius-sm);
          border: 1px solid var(--line-strong);
          padding: 12px;
          font-size: 13px;
          line-height: 1.6;
          background: var(--surface);
          color: var(--text);
          transition: border-color 0.2s ease;
        }
        .smart-rewrite-body textarea:focus {
          border-color: var(--accent);
          outline: none;
          box-shadow: 0 0 0 3px rgba(180, 83, 9, 0.08);
        }
        .smart-rewrite-badge {
          font-size: 10px;
          padding: 2px 8px;
          border-radius: 10px;
          background: var(--accent);
          color: var(--surface);
          font-weight: 700;
          letter-spacing: 0.3px;
        }
        .smart-rewrite-toggle {
          font-size: 18px;
          color: var(--accent);
          transition: transform 0.3s ease;
        }
        .smart-rewrite-toggle.open {
          transform: rotate(180deg);
        }
      `}</style>

      {/* Mode 1: Stories Dashboard List */}
      {mode === "list" && (
        <div className="star-fade-in">
          <section className="dashboard-hero" style={{ background: "linear-gradient(180deg, var(--surface), var(--surface-muted))" }}>
            <div>
              <span className="section-kicker">STAR 故事工坊</span>
              <h2>让你的项目经验，说出大厂级别的硬核故事。</h2>
              <p>采用结构化 STAR 向导，引导你丰富细节与数据，智能润色出可直接复制到简历的项目描述。</p>
            </div>
            <Button variant="primary" onClick={handleStartNew}>新建项目故事</Button>
          </section>

          <div className="dashboard-header-custom" style={{ marginTop: "24px" }}>
            <h3>已保存的项目故事 ({filteredStories.length})</h3>
            <input
              type="text"
              placeholder="搜索项目故事名称或内容..."
              className="dashboard-search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {filteredStories.length ? (
            <div className="card-grid-custom">
              {filteredStories.map((story) => (
                <Card 
                  key={story.id} 
                  title={story.title} 
                  action={
                    <Badge tone={getStyleBadgeTone(story.style)}>{getStyleLabel(story.style)}</Badge>
                  }
                  className="story-list-card"
                >
                  <div style={{ fontSize: "12.5px", color: "var(--muted)", display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical", overflow: "hidden", textOverflow: "ellipsis", margin: "10px 0 16px 0", lineHeight: "1.6" }}>
                    {story.full_text ? story.full_text.replace(/[#*`\-]/g, "") : "（空空如也，点击编辑生成润色文本）"}
                  </div>
                  <div style={{ display: "flex", gap: "8px", borderTop: "1px solid var(--line)", paddingTop: "12px", marginTop: "auto" }}>
                    <Button variant="secondary" onClick={() => handleEdit(story)} style={{ flex: 1, fontSize: "11px", padding: "6px" }}>编辑修改</Button>
                    <Button variant="secondary" onClick={() => handleClone(story)} style={{ fontSize: "11px", padding: "6px" }}>复制</Button>
                    <Button variant="danger" onClick={() => handleDelete(story.id)} style={{ fontSize: "11px", padding: "6px" }}>删除</Button>
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState 
              title={searchQuery ? "未找到匹配的故事" : "尚无项目故事"} 
              description={searchQuery ? "请更换关键词搜索，或新建一个项目故事。" : "按照 S-T-A-R 黄金向导撰写你的第一个项目细节吧。"} 
              actionLabel="新建项目故事"
              onAction={handleStartNew}
            />
          )}
        </div>
      )}

      {/* Mode 2: S-T-A-R Guided Wizard */}
      {mode === "wizard" && (
        <div className="star-fade-in page-stack">
          <div className="star-wizard-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
            <Button variant="ghost" onClick={() => setMode("list")} style={{ fontSize: "13px" }}>
              ← 返回列表
            </Button>
            <label className="field" style={{ margin: 0 }}>
              <span style={{ fontSize: "12px", color: "var(--muted)", textTransform: "none" }}>故事名称</span>
              <input
                type="text"
                placeholder="例如：腾讯微服务网关重构"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={{ width: "260px" }}
              />
            </label>
          </div>

          {/* Smart Rewrite Collapsible Panel */}
          <div className="smart-rewrite-panel">
            <div className="smart-rewrite-header" onClick={() => setSmartRewriteOpen(!smartRewriteOpen)}>
              <h4>
                ✨ 一键智能改写
                <span className="smart-rewrite-badge">推荐</span>
              </h4>
              <span className={`smart-rewrite-toggle ${smartRewriteOpen ? "open" : ""}`}>▼</span>
            </div>
            {smartRewriteOpen && (
              <div className="smart-rewrite-body">
                <p style={{ fontSize: "12px", color: "var(--muted)", margin: 0, lineHeight: "1.5" }}>
                  直接粘贴完整的项目经历描述（简历片段、面试草稿、甚至随意的笔记都可以），AI 将自动按 STAR 结构拆解并润色成简历级表达。
                </p>

                {/* Unified JD selection history import inside smart rewrite page */}
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", margin: "10px 0 14px 0" }}>
                  <span style={{ fontSize: "12.5px", fontWeight: "700", color: "var(--text)", display: "flex", alignItems: "center", gap: "6px" }}>
                    🔗 导入最近的简历与 JD 分析记录：
                  </span>
                  <select
                    value={selectedJdId}
                    onChange={handleJdSelect}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      fontSize: "13px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--line-strong)",
                      background: "var(--surface)",
                      color: "var(--text)",
                      outline: "none",
                      cursor: "pointer",
                      transition: "border-color 0.2s ease"
                    }}
                    onFocus={(e) => e.target.style.borderColor = "var(--accent)"}
                    onBlur={(e) => e.target.style.borderColor = "var(--line-strong)"}
                  >
                    <option value="">-- 选择分析记录 (一键加载该岗位的待修改片段) --</option>
                    {historyJds.map((item) => {
                      const name = item.input_json?.company || item.result_json?.draft?.company || "未命名公司";
                      const title = item.input_json?.title || item.result_json?.draft?.title || "未知岗位";
                      const adviceCount = item.resumeAdvice?.length || 0;
                      return (
                        <option key={item.id} value={item.id}>
                          {name} - {title} ({adviceCount} 条待改写建议)
                        </option>
                      );
                    })}
                  </select>
                </div>

                {selectedJdAdvice.some(item => getOriginalResumeText(item)) && (
                  <div className="quick-fill-advice-segments" style={{ margin: "12px 0", padding: "12px", background: "rgba(0,0,0,0.02)", borderRadius: "var(--radius-md)", border: "1px dashed var(--line)", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ fontSize: "12px", fontWeight: "700", color: "var(--text)", display: "flex", alignItems: "center", gap: "6px" }}>
                      🎯 <span>快捷填入待改写的原始简历片段：</span>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", maxHeight: "150px", overflowY: "auto", paddingRight: "4px" }}>
                      {selectedJdAdvice.map((item) => {
                        const originalText = getOriginalResumeText(item);
                        if (!originalText) return null;
                        return (
                          <div 
                            key={item.id} 
                            style={{ 
                              display: "flex", 
                              justifyContent: "space-between", 
                              alignItems: "center", 
                              padding: "8px 12px", 
                              background: "var(--surface)", 
                              border: "1px solid var(--line)", 
                              borderRadius: "var(--radius-sm)",
                              fontSize: "11px",
                              gap: "12px"
                            }}
                          >
                            <div style={{ display: "flex", flexDirection: "column", gap: "2px", flex: 1, minWidth: 0 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <span 
                                  style={{ 
                                    fontSize: "9px", 
                                    padding: "1px 4px", 
                                    borderRadius: "3px",
                                    fontWeight: "700",
                                    color: item.priority === "high" ? "#ef4444" : "#f59e0b",
                                    background: item.priority === "high" ? "rgba(239, 68, 68, 0.1)" : "rgba(245, 158, 11, 0.1)",
                                    border: `1px solid ${item.priority === "high" ? "rgba(239, 68, 68, 0.2)" : "rgba(245, 158, 11, 0.2)"}`
                                  }}
                                >
                                  {item.priority === "high" ? "必须改" : "建议改"}
                                </span>
                                <span style={{ fontWeight: "700", color: "var(--text)", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                                  {item.issue}
                                </span>
                              </div>
                              <span style={{ color: "var(--muted)", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                                建议：{item.suggestion}
                              </span>
                            </div>
                            <Button
                              variant="secondary"
                              style={{ fontSize: "11px", padding: "4px 8px", minHeight: "26px", height: "auto", flexShrink: 0 }}
                              onClick={() => {
                                const targetText = `${originalText}\n\n【修改目标】：针对以下简历问题进行针对性智能改写：\n- 问题缺陷：${item.issue}\n- 优化建议：${item.suggestion}`;
                                setSmartRewriteText(targetText);
                              }}
                            >
                              ✍️ 一键填入改写
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                <textarea
                  placeholder="在这里粘贴你的完整项目经历...\n\n例如：我在XX公司实习期间，参与了后端微服务网关的重构项目。当时系统的日均请求量已达到500万次，但旧网关存在单点故障和延迟高的问题。我负责设计新的网关架构，采用了Spring Cloud Gateway替换原有的Zuul方案，并引入了Redis做请求限流和缓存。最终网关的P99延迟从200ms降到了50ms，系统可用性从99.5%提升到99.99%。"
                  value={smartRewriteText}
                  onChange={(e) => setSmartRewriteText(e.target.value)}
                />
                
                {loadingSmartRewrite ? (
                  <StarLoadingAnimation isLoading={true} loadingText="正在深度分析并改写项目经历..." />
                ) : (
                  <Button
                    variant="primary"
                    onClick={handleSmartRewrite}
                    disabled={!smartRewriteText.trim() || smartRewriteText.trim().length < 10}
                    style={{ width: "100%", height: "42px", fontSize: "14px", fontWeight: "700" }}
                  >
                    🚀 一键智能改写（将自动填入 STAR 并跳转打磨）
                  </Button>
                )}
                <span style={{ fontSize: "10px", color: "var(--subtle)", textAlign: "center" }}>
                  每次改写将消耗 1 次生成额度 · 支持 10~8000 字的项目描述
                </span>
              </div>
            )}
          </div>

          <div className="card">
            {/* Step Bar */}
            <div className="wizard-step-bar">
              {steps.map((s, idx) => (
                <div 
                  key={s.key} 
                  className={`wizard-step-indicator ${idx === activeStep ? "active" : ""} ${idx < activeStep ? "completed" : ""}`}
                  onClick={() => setActiveStep(idx)}
                >
                  <div className="wizard-circle">{idx + 1}</div>
                  <span className="wizard-step-label">{s.label.split(" - ")[0]}</span>
                </div>
              ))}
            </div>

            {/* Split layout: Input Panel vs AI Suggestion / Import Panel */}
            <div className="wizard-layout">
              {/* Left Side: Input Box */}
              <div className="wizard-content-box" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <h4 style={{ color: "var(--accent)", margin: 0, fontSize: "15px", fontWeight: "700" }}>{steps[activeStep].label}</h4>
                <p style={{ fontSize: "12px", color: "var(--muted)", margin: 0 }}>{steps[activeStep].placeholder}</p>
                <textarea
                  placeholder="请输入真实的原始项目经历，哪怕只有几句话、甚至毫无逻辑的草稿也没关系，AI 会引导并重塑您的表达..."
                  style={{ width: "100%", height: "180px", resize: "none" }}
                  value={getStepValue(steps[activeStep].key)}
                  onChange={(e) => setStepValue(steps[activeStep].key, e.target.value)}
                />
                
                {/* Unified Configuration Panel (Always Visible to select before generation) */}
                <div className="card" style={{ padding: "16px", background: "var(--surface-muted)", marginTop: "12px", display: "flex", flexDirection: "column", gap: "12px", boxShadow: "none" }}>
                  <label className="field">
                    <span>关联参考的应聘 JD <small>(可选，AI将结合其要求定制修改建议)</small></span>
                    <select
                      value={selectedJdId}
                      onChange={handleJdSelect}
                    >
                      <option value="">-- 不关联 (使用通用打磨模式) --</option>
                      {historyJds.map((item) => {
                        const name = item.input_json?.company || item.result_json?.draft?.company || "未命名公司";
                        const title = item.input_json?.title || item.result_json?.draft?.title || "未知岗位";
                        return (
                          <option key={item.id} value={item.id}>
                            {name} - {title}
                          </option>
                        );
                      })}
                    </select>
                  </label>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                    <label className="field">
                      <span>选择 AI 模型</span>
                      <select
                        value={selectedConfigId}
                        onChange={(e) => setSelectedConfigId(e.target.value)}
                      >
                        <option value="">默认大模型 (全局配置)</option>
                        {modelConfigs.map((cfg) => (
                          <option key={cfg.id} value={cfg.id}>
                            {cfg.name || `${cfg.provider} - ${cfg.modelId}`} {cfg.enabled ? "" : "(未启用)"}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>润色表达风格</span>
                      <select
                        value={activeStyle}
                        onChange={(e) => setActiveStyle(e.target.value)}
                      >
                        <option value="standard">通用标准风</option>
                        <option value="big-tech">大厂硬核风</option>
                        <option value="start-up">敏捷突击风</option>
                      </select>
                    </label>
                  </div>
                </div>

                <div style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
                  <Button 
                    variant="ghost" 
                    onClick={() => setActiveStep((prev) => Math.max(0, prev - 1))} 
                    disabled={activeStep === 0}
                    style={{ flex: 1 }}
                  >
                    上一步
                  </Button>
                  
                  {activeStep < 3 ? (
                    <Button 
                      variant="secondary" 
                      onClick={() => setActiveStep((prev) => Math.min(3, prev + 1))}
                      style={{ flex: 1 }}
                    >
                      下一步
                    </Button>
                  ) : (
                    <Button 
                      variant="primary" 
                      onClick={() => setMode("polish")}
                      style={{ flex: 1 }}
                    >
                      前往智能打磨设置 ➔
                    </Button>
                  )}
                </div>
              </div>

              {/* Right Side: AI Assistant suggestion box OR One-click Import suggestions from JD */}
              <div className="wizard-content-box suggestion-panel" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                
                {/* Condition 1: If JD has been selected and has Resume Advice, display the Import list first */}
                {selectedJdAdvice.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "var(--text)" }}>💡 已选 JD 岗位改写优化建议</h4>
                      <Badge tone="info">支持一键导入</Badge>
                    </div>
                    <div className="advice-import-panel">
                      {selectedJdAdvice.map((item) => {
                        const originalText = getOriginalResumeText(item);
                        return (
                          <div key={item.id} className="advice-item-card">
                            <div style={{ color: "var(--accent)", fontWeight: "700" }}>⚠️ 【优化项】：{item.issue}</div>
                            <div style={{ color: "var(--muted)", margin: "2px 0" }}>建议：{item.suggestion}</div>
                            {item.example && (
                              <div style={{ padding: "6px", background: "var(--bg)", borderRadius: "4px", fontSize: "11px", color: "var(--text)", borderLeft: "3px solid var(--accent)" }}>
                                <strong>示例：</strong>{item.example}
                              </div>
                            )}
                            {originalText && (
                              <div style={{ padding: "6px", background: "var(--surface-muted)", borderRadius: "4px", fontSize: "11px", color: "var(--text)", borderLeft: "3px solid var(--line-strong)", marginTop: "6px" }}>
                                <strong>📄 关联原始简历片段 (未优化)：</strong>
                                <div style={{ marginTop: "4px", whiteSpace: "pre-wrap" }}>{originalText}</div>
                              </div>
                            )}
                            <div style={{ display: "flex", gap: "8px", marginTop: "8px", alignSelf: "flex-end", flexWrap: "wrap", justifyContent: "flex-end" }}>
                              <Button 
                                variant="secondary" 
                                style={{ fontSize: "11px", padding: "4px 8px", minHeight: "28px" }}
                                onClick={() => handleFillAdvice(item.example || item.suggestion)}
                              >
                                ✍️ 导入当前步骤 ({steps[activeStep].label.split(" - ")[0]})
                              </Button>
                              {originalText && (
                                <Button 
                                  variant="secondary" 
                                  style={{ fontSize: "11px", padding: "4px 8px", minHeight: "28px" }}
                                  onClick={() => handleImportAdviceToStar(originalText, "原始简历项目内容")}
                                >
                                  🚀 一键填入原始片段 (未优化)
                                </Button>
                              )}
                              <Button 
                                variant="primary" 
                                style={{ fontSize: "11px", padding: "4px 8px", minHeight: "28px" }}
                                onClick={() => handleImportAdviceToStar(item.example || item.suggestion, "优化改写示例")}
                              >
                                ✨ 一键填入优化示例
                              </Button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  // Condition 2: Regular AI Step Coach suggestion
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h4 style={{ margin: 0, fontSize: "13px", fontWeight: "700", color: "var(--text)" }}>🤖 AI 分步引导建议</h4>
                      <Button 
                        variant="ghost" 
                        onClick={handleGenerateSuggestion} 
                        disabled={loadingSuggestion}
                        style={{ fontSize: "11px", padding: "4px 8px", minHeight: "28px" }}
                      >
                        {loadingSuggestion ? "分析中..." : "✨ 获取本步 AI 指导"}
                      </Button>
                    </div>
                    
                    <div className="suggestion-box">
                      {loadingSuggestion ? (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "120px", gap: "10px" }}>
                          <span style={{ fontSize: "12px", color: "var(--muted)" }}>正在解析已填内容与 JD 上下文...</span>
                        </div>
                      ) : aiSuggestion ? (
                        <div>
                          {aiSuggestion.split("\n").map((line, i) => {
                            if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
                              return <li key={i} style={{ marginLeft: "10px", marginBottom: "6px", listStyleType: "disc" }}>{line.replace(/^[-*]\s*/, "")}</li>;
                            }
                            return <p key={i} style={{ marginBottom: "8px" }}>{line}</p>;
                          })}
                        </div>
                      ) : (
                        <p style={{ color: "var(--subtle)" }}>
                          点击右上角的“获取 AI 指导”按钮。AI 将分析你当前输入的碎片，为你提供补充数据、核心细节的方向指引，并列举大厂句型示例。
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Mode 3: Refinement Workspace */}
      {mode === "polish" && (
        <div className="star-fade-in page-stack">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <Button variant="ghost" onClick={() => setMode("wizard")} style={{ fontSize: "13px", display: "flex", alignItems: "center", gap: "6px" }}>
              ← 返回步骤向导
            </Button>
            <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700" }}>项目故事打磨空间</h3>
          </div>

          <div className="polish-layout">
            {/* Left Box: Controls & Style selection prior to generating */}
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <Card title="打磨设置与配置">
                <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                  
                  {/* Model Config Dropdown Selector */}
                  <div className="field">
                    <span>选择 AI 模型配置</span>
                    <select
                      value={selectedConfigId}
                      onChange={(e) => setSelectedConfigId(e.target.value)}
                    >
                      <option value="">默认大模型 (使用系统全局配置)</option>
                      {modelConfigs.map((cfg) => (
                        <option key={cfg.id} value={cfg.id}>
                          {cfg.name || `${cfg.provider} - ${cfg.modelId}`} {cfg.enabled ? "" : "(未启用)"}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Style Choice Selector */}
                  <div className="field">
                    <span>选择融合表达风格</span>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "4px" }}>
                      <button 
                        type="button" 
                        className={`style-btn ${activeStyle === "standard" ? "active" : ""}`}
                        onClick={() => setActiveStyle("standard")}
                      >
                        通用标准风
                      </button>
                      <button 
                        type="button" 
                        className={`style-btn ${activeStyle === "big-tech" ? "active" : ""}`}
                        onClick={() => setActiveStyle("big-tech")}
                      >
                        大厂硬核风
                      </button>
                      <button 
                        type="button" 
                        className={`style-btn ${activeStyle === "start-up" ? "active" : ""}`}
                        onClick={() => setActiveStyle("start-up")}
                      >
                        敏捷突击风
                      </button>
                    </div>
                  </div>

                  {/* STAR Fragments Summary Preview */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px", background: "var(--surface-muted)", padding: "12px", border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", marginTop: "6px" }}>
                    <span style={{ fontSize: "11px", color: "var(--muted)", fontWeight: "600" }}>当前已填碎片简览:</span>
                    <div style={{ fontSize: "11px", lineHeight: "1.5", color: "var(--text)", maxHeight: "150px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "4px" }}>
                      <div><strong>S:</strong> {situation || "未填"}</div>
                      <div><strong>T:</strong> {task || "未填"}</div>
                      <div><strong>A:</strong> {action || "未填"}</div>
                      <div><strong>R:</strong> {result || "未填"}</div>
                    </div>
                  </div>

                  <Button 
                    variant="primary" 
                    onClick={handlePolishStory}
                    disabled={loadingPolish}
                    style={{ marginTop: "12px", width: "100%", height: "40px" }}
                  >
                    {loadingPolish ? "正在打磨合成中..." : "✨ 开始智能融合打磨"}
                  </Button>
                  <span style={{ fontSize: "10px", color: "var(--subtle)", textAlign: "center" }}>提示：每次开始智能打磨将消耗 1 次简历分析额度。</span>
                </div>
              </Card>

              {/* Save & Cancel Actions */}
              <div style={{ display: "flex", gap: "12px" }}>
                <Button 
                  variant="primary" 
                  onClick={handleSaveStory}
                  disabled={!polishedText || loadingPolish}
                  style={{ flex: 1, fontWeight: "700" }}
                >
                  保存此故事至列表
                </Button>
                <Button 
                  variant="ghost" 
                  onClick={() => setMode("list")}
                  style={{ flex: 0.8 }}
                >
                  取消并返回
                </Button>
              </div>
            </div>

            {/* Right Box: Visual polished Resume Markdown preview */}
            <div className="polished-workspace-box">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line)", paddingBottom: "12px", marginBottom: "16px" }}>
                <strong style={{ fontSize: "13px", color: "var(--text)" }}>简历格式精美效果预览</strong>
                <Button 
                  variant="ghost" 
                  onClick={() => {
                    void navigator.clipboard.writeText(polishedText);
                    alert("已复制项目话术到剪贴板！");
                  }}
                  disabled={!polishedText}
                  style={{ fontSize: "11px", padding: "4px 8px", minHeight: "28px" }}
                >
                  📋 一键复制项目话术
                </Button>
              </div>

              <div style={{ flex: 1, overflowY: "auto", maxHeight: "480px" }}>
                {loadingPolish ? (
                  <StarLoadingAnimation isLoading={true} loadingText="大语言模型正在对项目碎片进行黄金重塑与润色中..." />
                ) : polishedText ? (
                  renderPolishedMarkdown(polishedText)
                ) : (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "180px", color: "var(--subtle)", fontSize: "13px" }}>
                    请在左侧选择你心仪的模型和想要展示的简历风格，然后点击【开始智能打磨】。
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
