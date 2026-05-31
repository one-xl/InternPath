(function() {
  console.log("[InternPath] Content script loaded.");

  // Inject a beautiful floating container on the page
  const container = document.createElement("div");
  container.id = "internpath-floating-widget";
  
  // Style the container
  Object.assign(container.style, {
    position: "fixed",
    right: "20px",
    bottom: "100px",
    zIndex: "999999",
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
  });

  const buttonStyle = {
    color: "#ffffff",
    border: "none",
    borderRadius: "20px",
    padding: "10px 16px",
    fontSize: "13px",
    fontWeight: "600",
    cursor: "pointer",
    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)",
    display: "flex",
    alignItems: "center",
    transition: "transform 0.15s, opacity 0.15s",
    minWidth: "120px",
    justifyContent: "center"
  };

  // Button 1: Autofill Webpage
  const autofillBtn = document.createElement("button");
  autofillBtn.innerHTML = `<span style="font-size: 14px; margin-right: 6px;">📝</span>自动回填网页`;
  Object.assign(autofillBtn.style, buttonStyle, {
    background: "linear-gradient(135deg, #0ea5e9, #2563eb)"
  });

  // Button 2: Import Backend
  const importBtn = document.createElement("button");
  importBtn.innerHTML = `<span style="font-size: 14px; margin-right: 6px;">📥</span>一键后台分析`;
  Object.assign(importBtn.style, buttonStyle, {
    background: "linear-gradient(135deg, #10b981, #059669)"
  });

  // Hover animations
  [autofillBtn, importBtn].forEach(btn => {
    btn.addEventListener("mouseenter", () => {
      btn.style.transform = "scale(1.05)";
    });
    btn.addEventListener("mouseleave", () => {
      btn.style.transform = "scale(1.0)";
    });
  });

  container.appendChild(autofillBtn);
  container.appendChild(importBtn);
  document.body.appendChild(container);

  // 抗噪双端净化器，去除推荐、举报、公司和按钮垃圾信息
  function cleanJdText(text) {
    if (!text) return "";
    
    let cleanText = text;
    
    // A. 净化头部：如果在最前面 400 字符内，发现了核心职责要求的起点词，我们可以切掉前置的冗余卡片信息
    const startKeywords = ["岗位职责", "职位描述", "工作职责", "岗位要求", "职责描述", "工作内容", "任务要求", "任职要求", "岗位职责:"];
    let firstStartIdx = -1;
    
    for (const startKw of startKeywords) {
      const idx = cleanText.indexOf(startKw);
      if (idx !== -1 && idx < 400) {
        if (firstStartIdx === -1 || idx < firstStartIdx) {
          firstStartIdx = idx;
        }
      }
    }
    
    if (firstStartIdx !== -1) {
      const discardedPart = cleanText.substring(0, firstStartIdx);
      const isNoise = discardedPart.includes("收藏") || 
                      discardedPart.includes("立即申请") || 
                      discardedPart.includes("HR") || 
                      discardedPart.includes("发私信") || 
                      discardedPart.includes("薪资") || 
                      discardedPart.includes("面议");
      if (isNoise) {
        cleanText = cleanText.substring(firstStartIdx);
      }
    }

    // B. 净化尾部：如果出现以下无关词，切除其后所有字符
    const cutKeywords = [
      "牛客安全提示",
      "安全提示",
      "为你推荐",
      "相似职位",
      "更多相似职位",
      "工作地址",
      "公司介绍",
      "团队介绍",
      "企业介绍",
      "工商信息",
      "查看其他",
      "立即举报",
      "举报取",
      "完善信息",
      "发私信",
      "笔试题目",
      "面试经验",
      "面试短评"
    ];
    
    for (const kw of cutKeywords) {
      const idx = cleanText.indexOf(kw);
      if (idx !== -1) {
        cleanText = cleanText.substring(0, idx);
      }
    }
    
    // C. 移除一些孤立的残留按钮词
    cleanText = cleanText.replace(/立即申请/g, "");
    cleanText = cleanText.replace(/收藏/g, "");
    cleanText = cleanText.replace(/取消/g, "");
    cleanText = cleanText.replace(/确定/g, "");
    
    return cleanText.trim();
  }

  // 智能且鲁棒的 JD 详情语义抓取器
  function getJdSemanticText() {
    // 1. 尝试使用常规已知的选择器
    const commonSelectors = [
      ".job-sec-text", 
      ".detail-content .job-sec .text", 
      ".job-detail .text", 
      ".job-detail-section .text",
      ".job-detail-content",
      ".detail-content",
      ".job-desc",
      ".job-description",
      ".job-detail-box",
      ".job-detail-box .text",
      ".job-sec .text",
      ".post-item__description",
      ".job-detail"
    ];
    for (const sel of commonSelectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim().length > 30) {
        return el.textContent.trim();
      }
    }

    // 2. 语义锚点查找
    const headers = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6, div, span, p, strong, li"));
    const keywords = ["职位描述", "岗位职责", "职位详情", "岗位要求", "工作职责", "任职条件", "任职要求", "工作内容", "JD"];
    let foundTextParts = [];
    
    for (const h of headers) {
      const txt = h.textContent.trim();
      if (txt.length > 0 && txt.length < 15 && keywords.includes(txt)) {
        let sibling = h.nextElementSibling;
        let collectedCount = 0;
        let tempParts = [];
        
        while (sibling && collectedCount < 5) {
          const siblingTxt = sibling.textContent.trim();
          const stopKeywords = ["为你推荐", "相似职位", "安全提示", "公司介绍", "查看其他", "举报"];
          if (stopKeywords.some(sk => siblingTxt.includes(sk)) && siblingTxt.length < 30) {
            break;
          }
          
          if (siblingTxt.length > 15) {
            tempParts.push(siblingTxt);
            collectedCount++;
          }
          sibling = sibling.nextElementSibling;
        }
        
        if (tempParts.length > 0) {
          foundTextParts.push(txt + "\n" + tempParts.join("\n"));
        }
      }
    }

    if (foundTextParts.length > 0) {
      const uniqueParts = [...new Set(foundTextParts)];
      const merged = uniqueParts.join("\n\n").trim();
      if (merged.length > 30) {
        return merged;
      }
    }
    
    return "";
  }

  // Scraper Logic
  function extractJobData() {
    const url = window.location.href;
    let title = "";
    let company = "";
    let salary = "";
    let location = "";
    let jd = "";

    if (url.includes("zhipin.com")) {
      title = (document.querySelector(".job-banner .name h1") || 
               document.querySelector(".name h1") || 
               document.querySelector(".job-title") || 
               document.querySelector(".title-box h1") || 
               {textContent: ""}).textContent.trim();
               
      company = (document.querySelector(".company-info a") || 
                 document.querySelector(".company-info .name") || 
                 document.querySelector(".company-text a") || 
                 document.querySelector(".company-name") || 
                 document.querySelector(".brand-name") || 
                 {textContent: ""}).textContent.trim();
                 
      salary = (document.querySelector(".salary") || 
                document.querySelector(".job-banner .salary") || 
                document.querySelector(".salary-box .salary") || 
                {textContent: ""}).textContent.trim();
                
      const locEl = document.querySelector(".job-banner .text") || document.querySelector(".info-primary .text-desc");
      if (locEl) {
        location = locEl.textContent.trim().split(" ")[0] || "";
      }
      
      const detailContainer = document.querySelector(".job-detail") || 
                              document.querySelector(".detail-content") ||
                              document.querySelector(".job-sec-text") ||
                              document.querySelector(".job-detail-section");
      if (detailContainer) {
        jd = detailContainer.innerText || detailContainer.textContent || "";
      }
    } else if (url.includes("nowcoder.com")) {
      title = (document.querySelector(".job-name") || 
               document.querySelector(".jobs-name") || 
               document.querySelector(".detail-title") || 
               document.querySelector("h1") || 
               {textContent: ""}).textContent.trim();
               
      company = (document.querySelector(".company-name") || 
                 document.querySelector(".company-title") || 
                 document.querySelector(".company-info") || 
                 {textContent: ""}).textContent.trim();
                 
      salary = (document.querySelector(".job-salary") || 
                document.querySelector(".salary") || 
                document.querySelector(".jobs-salary") || 
                {textContent: ""}).textContent.trim();
                
      location = (document.querySelector(".job-city") || 
                  document.querySelector(".city") || 
                  document.querySelector(".jobs-city") || 
                  {textContent: ""}).textContent.trim();
                  
      const detailContainer = document.querySelector(".job-detail-content") || 
                              document.querySelector(".detail-content") || 
                              document.querySelector(".job-desc") || 
                              document.querySelector(".post-item__description");
      if (detailContainer) {
        jd = detailContainer.innerText || detailContainer.textContent || "";
      }
    }

    // 如果常规选择器抓取的 jd 为空，启用语义自愈匹配器
    if (!jd || jd.length < 10) {
      jd = getJdSemanticText();
    }

    // 无论以何种方式抓取，均运行抗噪双端净化
    jd = cleanJdText(jd);

    return {
      title: title || "未知职位",
      company: company || "未知公司",
      location: location || "北京",
      salary_range: salary || "15k-25k",
      jd_text: jd || "无详情",
      source_url: url
    };
  }

  // Toast Alerts
  function showToast(message, isError = false) {
    const toast = document.createElement("div");
    Object.assign(toast.style, {
      position: "fixed",
      right: "20px",
      bottom: "200px",
      zIndex: "999999",
      background: isError ? "#f43f5e" : "#10b981",
      color: "#ffffff",
      padding: "12px 20px",
      borderRadius: "8px",
      boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.3)",
      fontSize: "13px",
      fontWeight: "600"
    });
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // Toast / Overlay UI for Match feedback
  function showFeedback(host, res) {
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed",
      right: "20px",
      bottom: "200px",
      zIndex: "999999",
      width: "300px",
      padding: "16px",
      background: "rgba(15, 23, 42, 0.95)",
      backdropFilter: "blur(12px)",
      border: "1px solid rgba(56, 189, 248, 0.4)",
      borderRadius: "12px",
      boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
      color: "#f8fafc",
      fontSize: "13px",
      lineHeight: "1.5"
    });

    const match = res.matchResult;
    const passed = match.passed;
    const matchScoreStr = match.stage1_score ? `${(match.stage1_score * 100).toFixed(0)}%` : "0%";
    
    overlay.innerHTML = `
      <div style="font-weight: 700; font-size: 14px; margin-bottom: 8px; color: ${passed ? '#10b981' : '#f43f5e'}; display: flex; align-items: center; gap: 6px;">
        <span>${passed ? '✅' : '⚠️'}</span>
        ${passed ? '职位匹配成功！' : '粗筛未通过'}
      </div>
      <div style="margin-bottom: 6px;"><strong>公司:</strong> ${extractJobData().company}</div>
      <div style="margin-bottom: 6px;"><strong>岗位:</strong> ${extractJobData().title}</div>
      <div style="margin-bottom: 6px;"><strong>月薪估算:</strong> ${res.salary_monthly_k}k/月</div>
      <div style="margin-bottom: 6px;"><strong>技术匹配度:</strong> <span style="font-weight: 600; color: #38bdf8">${matchScoreStr}</span></div>
      <div style="margin-bottom: 10px; color: #94a3b8; font-size: 12px; border-top: 1px solid #334155; padding-top: 8px;">
        ${match.reason}
      </div>
      <div style="display: flex; gap: 8px;">
        <button id="internpath-view-btn" style="flex: 1; padding: 6px; background: #334155; border: none; border-radius: 4px; color: #f8fafc; font-size: 12px; cursor: pointer;">查看工作台</button>
        <button id="internpath-close-btn" style="padding: 6px 12px; background: transparent; border: 1px solid #475569; border-radius: 4px; color: #94a3b8; font-size: 12px; cursor: pointer;">关闭</button>
      </div>
    `;

    document.body.appendChild(overlay);

    overlay.querySelector("#internpath-close-btn").addEventListener("click", () => {
      overlay.remove();
    });

    overlay.querySelector("#internpath-view-btn").addEventListener("click", () => {
      window.open(host.replace("/api", ""));
      overlay.remove();
    });

    setTimeout(() => {
      if (document.body.contains(overlay)) {
        overlay.remove();
      }
    }, 12000);
  }

  // 1. Autofill Button click handler
  autofillBtn.addEventListener("click", () => {
    autofillBtn.disabled = true;
    autofillBtn.style.opacity = "0.7";
    autofillBtn.innerHTML = `回填中...`;

    const jobData = extractJobData();
    chrome.runtime.sendMessage({ action: "autofill", data: jobData }, (response) => {
      autofillBtn.disabled = false;
      autofillBtn.style.opacity = "1.0";
      autofillBtn.innerHTML = `<span style="font-size: 14px; margin-right: 6px;">📝</span>自动回填网页`;

      if (response && response.success) {
        showToast("已自动回填并跳转至在线工作台！");
      } else {
        showToast("未检测到已打开的决策台网页，请先在浏览器打开并登录决策台主页。", true);
      }
    });
  });

  // 2. Direct Import Button click handler
  importBtn.addEventListener("click", () => {
    importBtn.disabled = true;
    importBtn.style.opacity = "0.7";
    importBtn.innerHTML = `导入中...`;

    chrome.storage.local.get(["internpathHost", "internpathToken"], (items) => {
      const host = items.internpathHost || "http://localhost:8787";
      const token = items.internpathToken || "";
      const jobData = extractJobData();

      const headers = {
        "Content-Type": "application/json"
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      fetch(`${host}/api/jobs/import`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(jobData)
      })
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error ${response.status}`);
        }
        return response.json();
      })
      .then(res => {
        importBtn.innerHTML = `<span style="font-size: 14px; margin-right: 6px;">📥</span>一键后台分析`;
        importBtn.disabled = false;
        importBtn.style.opacity = "1.0";
        showFeedback(host, res);
      })
      .catch(err => {
        console.error("[InternPath] Import failed:", err);
        importBtn.innerHTML = `<span style="font-size: 14px; margin-right: 6px;">📥</span>一键后台分析`;
        importBtn.disabled = false;
        importBtn.style.opacity = "1.0";
        showToast("导入失败，请检查配置或确认后端服务已启动！", true);
      });
    });
  });

  // 3. 自动检测并触发静默回填（支持 SPA 单页应用频繁切换与延迟渲染自愈）
  let lastJobUrl = "";
  let lastJobTitle = "";
  let lastJobCompany = "";

  function checkAndAutoTrigger() {
    try {
      const jobData = extractJobData();
      // 只有在职位名称不是"未知职位"，且岗位详情不是"无详情"时，才视为加载完成的有效职位
      if (jobData && jobData.title !== "未知职位" && jobData.jd_text !== "无详情") {
        // 如果当前职位的 URL、名称或公司有任何变化，则触发回填
        if (jobData.source_url !== lastJobUrl || jobData.title !== lastJobTitle || jobData.company !== lastJobCompany) {
          lastJobUrl = jobData.source_url;
          lastJobTitle = jobData.title;
          lastJobCompany = jobData.company;

          console.log("[InternPath] 检测到职位发生改变或加载完成，自动发起静默回填:", jobData.title);
          
          chrome.runtime.sendMessage({ action: "autofill", data: jobData, isAuto: true }, (response) => {
            if (response && response.success) {
              console.log("[InternPath] 职位已成功自动静默回填至工作台:", jobData.title);
            }
          });
        }
      }
    } catch (e) {
      console.error("[InternPath] 自动检测回填执行异常:", e);
    }
  }

  // 采用 1.5 秒间隔轮询机制，既保障了 SPA 切换的即时响应与延迟加载的自动修复，又确保极低的 CPU 消耗
  setInterval(checkAndAutoTrigger, 1500);
})();
