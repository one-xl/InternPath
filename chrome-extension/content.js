(function() {
  console.log("[InternPath] Content script loaded.");

  // Inject a beautiful floating button on the page
  const button = document.createElement("button");
  button.id = "internpath-import-btn";
  button.innerHTML = `
    <span style="font-size: 16px; margin-right: 6px;">🧭</span>
    导入 InternPath
  `;
  
  // Style the floating button
  Object.assign(button.style, {
    position: "fixed",
    right: "20px",
    bottom: "100px",
    zIndex: "999999",
    background: "linear-gradient(135deg, #0ea5e9, #2563eb)",
    color: "#ffffff",
    border: "none",
    borderRadius: "24px",
    padding: "12px 20px",
    fontSize: "14px",
    fontWeight: "600",
    cursor: "pointer",
    boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -4px rgba(0, 0, 0, 0.3)",
    display: "flex",
    alignItems: "center",
    transition: "transform 0.2s, opacity 0.2s",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
  });

  button.addEventListener("mouseenter", () => {
    button.style.transform = "scale(1.05)";
  });
  button.addEventListener("mouseleave", () => {
    button.style.transform = "scale(1.0)";
  });

  document.body.appendChild(button);

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
      
      jd = (document.querySelector(".job-sec-text") || 
            document.querySelector(".detail-content .job-sec .text") || 
            document.querySelector(".job-detail .text") || 
            document.querySelector(".job-detail-section .text") || 
            {textContent: ""}).textContent.trim();
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
                  
      jd = (document.querySelector(".job-detail-content") || 
            document.querySelector(".detail-content") || 
            document.querySelector(".job-desc") || 
            {textContent: ""}).textContent.trim();
    }

    return {
      title: title || "未知职位",
      company: company || "未知公司",
      location: location || "北京",
      salary_range: salary || "15k-25k",
      jd_text: jd || "无详情",
      source_url: url
    };
  }

  // Toast / Overlay UI for Match feedback
  function showFeedback(host, res) {
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed",
      right: "20px",
      bottom: "160px",
      zIndex: "999999",
      width: "300px",
      padding: "16px",
      background: "rgba(15, 23, 42, 0.95)",
      backdropFilter: "blur(12px)",
      border: "1px solid rgba(56, 189, 248, 0.4)",
      borderRadius: "12px",
      boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 10px 10px -5px rgba(0, 0, 0, 0.5)",
      color: "#f8fafc",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
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

    // Auto remove after 10s
    setTimeout(() => {
      if (document.body.contains(overlay)) {
        overlay.remove();
      }
    }, 10000);
  }

  function showToast(message, isError = false) {
    const toast = document.createElement("div");
    Object.assign(toast.style, {
      position: "fixed",
      right: "20px",
      bottom: "160px",
      zIndex: "999999",
      background: isError ? "#f43f5e" : "#10b981",
      color: "#ffffff",
      padding: "10px 18px",
      borderRadius: "8px",
      boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.3)",
      fontSize: "13px",
      fontWeight: "600",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    });
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  // Handle click action
  button.addEventListener("click", () => {
    button.disabled = true;
    button.style.opacity = "0.7";
    button.textContent = "导入中...";

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
        button.innerHTML = `<span style="font-size: 16px; margin-right: 6px;">🧭</span> 导入 InternPath`;
        button.disabled = false;
        button.style.opacity = "1.0";
        showFeedback(host, res);
      })
      .catch(err => {
        console.error("[InternPath] Import failed:", err);
        button.innerHTML = `<span style="font-size: 16px; margin-right: 6px;">🧭</span> 导入 InternPath`;
        button.disabled = false;
        button.style.opacity = "1.0";
        showToast("导入失败，请检查配置或确认后端服务已启动！", true);
      });
    });
  });
})();
