(function() {
  console.log("[InternPath] Content script loaded.");

  // 1. Sleek Floating Trigger (Round Bubble)
  const bubble = document.createElement("div");
  bubble.id = "internpath-floating-bubble";
  bubble.innerHTML = "🧭";
  
  // Style bubble
  Object.assign(bubble.style, {
    position: "fixed",
    right: "24px",
    bottom: "80px",
    zIndex: "999999",
    width: "48px",
    height: "48px",
    borderRadius: "50%",
    background: "linear-gradient(135deg, #0ea5e9, #2563eb)",
    color: "#ffffff",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "22px",
    fontWeight: "bold",
    cursor: "pointer",
    boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.4)",
    userSelect: "none",
    transition: "transform 0.2s ease, box-shadow 0.2s ease"
  });

  // 2. Drawer Panel (Smart Panel)
  const panel = document.createElement("div");
  panel.id = "internpath-smart-panel";
  
  // Style panel
  Object.assign(panel.style, {
    position: "fixed",
    right: "24px",
    bottom: "140px",
    zIndex: "999999",
    width: "330px",
    maxHeight: "560px",
    background: "rgba(15, 23, 42, 0.98)",
    backdropFilter: "blur(12px)",
    border: "1px solid rgba(56, 189, 248, 0.3)",
    borderRadius: "12px",
    boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    color: "#f8fafc",
    padding: "16px",
    boxSizing: "border-box",
    display: "none",
    flexDirection: "column",
    gap: "12px",
    overflowY: "auto"
  });

  // Construct Panel HTML
  panel.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 8px;">
      <span style="font-weight: 700; font-size: 14px; color: #38bdf8; display: flex; align-items: center; gap: 6px;">
        <span>🧭</span> InternPath 智能求职助手
      </span>
      <span id="internpath-close-panel" style="font-size: 16px; cursor: pointer; color: #94a3b8; transition: color 0.15s;">&times;</span>
    </div>
    
    <!-- Resume Selector Section -->
    <div class="form-group" style="display: flex; flex-direction: column; gap: 4px;">
      <label style="font-size: 11px; color: #94a3b8; font-weight: 600;">选择上传的简历</label>
      <select id="internpath-resume-select" style="background: #1e293b; border: 1px solid #334155; border-radius: 6px; color: #f8fafc; padding: 6px 8px; font-size: 12px; outline: none; width: 100%;">
        <option value="">正在加载简历...</option>
      </select>
    </div>

    <!-- Scraped JD Text Section -->
    <div class="form-group" style="display: flex; flex-direction: column; gap: 4px;">
      <label style="font-size: 11px; color: #94a3b8; font-weight: 600;">投递岗位职责描述 (JD)</label>
      <textarea id="internpath-jd-textarea" placeholder="抓取或在此粘贴目标岗位的 JD 描述..." style="background: #1e293b; border: 1px solid #334155; border-radius: 6px; color: #f8fafc; padding: 6px 8px; font-size: 12px; outline: none; resize: vertical; min-height: 80px; width: 100%; box-sizing: border-box; line-height: 1.4;"></textarea>
    </div>

    <!-- Scanned Form Fields Status -->
    <div id="internpath-scan-status" style="background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px 10px; font-size: 11px; color: #cbd5e1; line-height: 1.4;">
      🔍 正在扫描页面表单元素...
    </div>

    <!-- Action Buttons -->
    <div style="display: flex; flexDirection: column; gap: 8px; margin-top: 4px;">
      <button id="internpath-smartfill-btn" style="width: 100%; color: #ffffff; border: none; border-radius: 6px; padding: 9px; font-size: 12px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; background: linear-gradient(135deg, #0ea5e9, #2563eb); display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 6px;">
        <span>⚡</span> 智能填表网申
      </button>
      
      <div id="internpath-job-actions" style="display: flex; gap: 8px;">
        <button id="internpath-autofill-btn" style="flex: 1; color: #ffffff; border: none; border-radius: 6px; padding: 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; background: #334155; display: flex; align-items: center; justify-content: center; gap: 2px;">
          <span>📝</span> 自动回填职位
        </button>
        <button id="internpath-import-btn" style="flex: 1; color: #ffffff; border: none; border-radius: 6px; padding: 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; background: linear-gradient(135deg, #10b981, #059669); display: flex; align-items: center; justify-content: center; gap: 2px;">
          <span>📥</span> 一键后台分析
        </button>
      </div>
    </div>
  `;

  // UI Event Listeners
  bubble.addEventListener("mouseenter", () => {
    bubble.style.transform = "scale(1.08)";
    bubble.style.boxShadow = "0 12px 28px -4px rgba(0, 0, 0, 0.5)";
  });
  bubble.addEventListener("mouseleave", () => {
    bubble.style.transform = "scale(1.0)";
    bubble.style.boxShadow = "0 10px 25px -5px rgba(0, 0, 0, 0.4)";
  });
  bubble.addEventListener("click", () => {
    if (panel.style.display === "none") {
      panel.style.display = "flex";
      loadResumesDropdown();
      updateScanStatusUI();
    } else {
      panel.style.display = "none";
    }
  });

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  const closePanelSpan = panel.querySelector("#internpath-close-panel");
  closePanelSpan.addEventListener("mouseenter", () => closePanelSpan.style.color = "#f8fafc");
  closePanelSpan.addEventListener("mouseleave", () => closePanelSpan.style.color = "#94a3b8");
  closePanelSpan.addEventListener("click", () => panel.style.display = "none");

  const jdTextarea = panel.querySelector("#internpath-jd-textarea");
  const resumeSelect = panel.querySelector("#internpath-resume-select");
  const smartFillBtn = panel.querySelector("#internpath-smartfill-btn");
  const autofillBtn = panel.querySelector("#internpath-autofill-btn");
  const importBtn = panel.querySelector("#internpath-import-btn");

  // Load Job Scraper data on load (pre-fills JD if on Boss/Nowcoder)
  let initialJobData = null;
  try {
    initialJobData = extractJobData();
    if (initialJobData && initialJobData.jd_text && initialJobData.jd_text !== "无详情") {
      jdTextarea.value = initialJobData.jd_text;
    }
  } catch (e) {
    console.log("[InternPath] Initial job scrape skipped.");
  }

  // Toggle Job Actions depending on whether JD scraper yields results
  function updateJobActionsVisibility() {
    const jobActionsEl = panel.querySelector("#internpath-job-actions");
    if (initialJobData && initialJobData.title !== "未知职位") {
      jobActionsEl.style.display = "flex";
    } else {
      jobActionsEl.style.display = "none";
    }
  }
  updateJobActionsVisibility();

  // Load Resumes Dropdown from Backend
  function loadResumesDropdown() {
    chrome.runtime.sendMessage({ action: "get_resumes" }, (response) => {
      resumeSelect.innerHTML = "";
      if (response && response.success) {
        const resumes = response.resumes || [];
        if (resumes.length === 0) {
          const opt = document.createElement("option");
          opt.value = "";
          opt.textContent = "无可用简历，请先登录工作台上传";
          resumeSelect.appendChild(opt);
        } else {
          resumes.forEach(r => {
            const opt = document.createElement("option");
            opt.value = r.id;
            opt.textContent = `${r.name} (${(r.size / 1024).toFixed(0)}KB)`;
            resumeSelect.appendChild(opt);
          });
        }
      } else {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "⚠️ 请先在插件菜单中登录工作台账号";
        resumeSelect.appendChild(opt);
      }
    });
  }

  // DOM Form Scanning Logic
  function scanFormFields() {
    const fields = [];
    const inputs = Array.from(document.querySelectorAll("input, textarea"));

    function searchText(el, kws) {
      const attrSearch = [
        el.id,
        el.name,
        el.placeholder,
        el.getAttribute("aria-label"),
        el.className
      ].filter(Boolean).map(s => s.toLowerCase());

      let labelText = "";
      if (el.id) {
        const label = document.querySelector(`label[for="${el.id}"]`);
        if (label) labelText = label.textContent;
      }
      if (!labelText) {
        const parentLabel = el.closest("label");
        if (parentLabel) labelText = parentLabel.textContent;
      }
      if (!labelText) {
        let prev = el.previousElementSibling;
        while (prev) {
          if (prev.tagName.match(/^(LABEL|DIV|SPAN)$/i)) {
            labelText = prev.textContent;
            break;
          }
          prev = prev.previousElementSibling;
        }
      }

      labelText = labelText.toLowerCase();

      return kws.some(kw => {
        const kwL = kw.toLowerCase();
        if (labelText.includes(kwL)) return true;
        return attrSearch.some(attr => attr.includes(kwL));
      });
    }

    inputs.forEach(el => {
      // Avoid hidden inputs
      if (el.type === "hidden" || el.style.display === "none" || el.style.visibility === "hidden") {
        return;
      }

      let fieldType = null;

      if (searchText(el, ["自我评价", "自我介绍", "综合素质", "求职特长", "个人评价", "self"])) {
        fieldType = "self_evaluation";
      } else if (searchText(el, ["项目经历", "项目描述", "项目介绍", "开发经历", "project"])) {
        fieldType = "projects";
      } else if (searchText(el, ["工作经历", "工作描述", "实习经历", "工作表现", "work", "experience", "internship"])) {
        fieldType = "work_experience";
      } else if (searchText(el, ["专业技能", "技能清单", "技术栈", "掌握技能", "skill", "技能"])) {
        fieldType = "skills";
      } else if (searchText(el, ["个人优势", "核心亮点", "优势介绍", "advantage"])) {
        fieldType = "advantages";
      } else if (searchText(el, ["姓名", "中文名", "真实姓名", "name"])) {
        fieldType = "name";
      } else if (searchText(el, ["手机", "电话", "联系电话", "手机号", "phone", "mobile"])) {
        fieldType = "phone";
      } else if (searchText(el, ["邮箱", "电子邮箱", "email", "mail"])) {
        fieldType = "email";
      } else if (searchText(el, ["学校", "毕业学校", "就读院校", "school", "university"])) {
        fieldType = "school";
      } else if (searchText(el, ["专业", "就读专业", "major"])) {
        fieldType = "major";
      } else if (searchText(el, ["学历", "学位", "highest degree", "degree"])) {
        fieldType = "degree";
      }

      if (fieldType) {
        fields.push({
          element: el,
          type: fieldType
        });
      }
    });

    return fields;
  }

  // Update Scanned Field Labels in UI
  function updateScanStatusUI() {
    const scanStatusDiv = panel.querySelector("#internpath-scan-status");
    const fields = scanFormFields();
    if (fields.length === 0) {
      scanStatusDiv.innerHTML = "🔍 未检测到支持智能填写或个人信息的表单输入项。";
    } else {
      const typeLabels = {
        name: "姓名",
        phone: "手机",
        email: "邮箱",
        school: "学校",
        major: "专业",
        degree: "学历",
        self_evaluation: "自我评价",
        projects: "项目经历",
        work_experience: "工作经历",
        skills: "专业技能",
        advantages: "个人优势"
      };
      const names = [...new Set(fields.map(f => typeLabels[f.type] || f.type))];
      scanStatusDiv.innerHTML = `✅ 检测到 ${fields.length} 个表单输入项：<br/><strong>${names.join("、")}</strong>`;
    }
  }

  // React/Vue State Compatible Input filler
  function setElementValue(el, val) {
    if (!el) return;
    const lastValue = el.value;
    el.value = val;

    // Trigger React binding sync
    const tracker = el._valueTracker;
    if (tracker) {
      tracker.setValue(lastValue);
    }

    // Dispatch events for React, Vue and standard JS listeners
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // Smart Fill action handler
  smartFillBtn.addEventListener("click", () => {
    const resumeId = resumeSelect.value;
    if (!resumeId) {
      showToast("请先选择用于生成的简历", true);
      return;
    }

    const jdText = jdTextarea.value.trim();
    if (!jdText || jdText.length < 20) {
      showToast("请输入目标岗位的 JD 描述以提供优化上下文", true);
      return;
    }

    const fields = scanFormFields();
    if (fields.length === 0) {
      showToast("页面上未找到匹配的输入框或表单字段", true);
      return;
    }

    // Collect fields that need AI tailoring
    const AI_FIELDS = ["self_evaluation", "projects", "work_experience", "skills", "advantages"];
    const fieldsToTailor = [...new Set(fields.filter(f => AI_FIELDS.includes(f.type)).map(f => f.type))];

    smartFillBtn.disabled = true;
    smartFillBtn.innerHTML = `正在生成 AI 定制文案...`;

    chrome.runtime.sendMessage({
      action: "tailor_fields",
      data: {
        resume_file_id: resumeId,
        jd_text: jdText,
        fields: fieldsToTailor
      }
    }, (response) => {
      smartFillBtn.disabled = false;
      smartFillBtn.innerHTML = `<span>⚡</span> 智能填表网申`;

      if (response && response.success) {
        const tailored = response.tailored_data || {};
        const profile = response.profile || {};

        let filledCount = 0;
        fields.forEach(f => {
          let valueToFill = "";
          if (AI_FIELDS.includes(f.type)) {
            valueToFill = tailored[f.type];
          } else {
            valueToFill = profile[f.type];
          }

          if (valueToFill) {
            setElementValue(f.element, valueToFill);
            filledCount++;
          }
        });

        showToast(`已自动帮您填入 ${filledCount} 个匹配字段！`);
      } else {
        const err = (response && response.error) || "请求超时";
        showToast(`AI 定制失败: ${err}`, true);
      }
    });
  });

  // Scraping logic helpers
  function cleanJdText(text) {
    if (!text) return "";
    let cleanText = text;
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
      const isNoise = discardedPart.includes("收藏") || discardedPart.includes("立即申请") || discardedPart.includes("HR") || discardedPart.includes("发私信") || discardedPart.includes("薪资") || discardedPart.includes("面议");
      if (isNoise) {
        cleanText = cleanText.substring(firstStartIdx);
      }
    }
    const cutKeywords = ["牛客安全提示", "安全提示", "为你推荐", "相似职位", "更多相似职位", "工作地址", "公司介绍", "团队介绍", "企业介绍", "工商信息", "查看其他", "立即举报", "举报取", "完善信息", "发私信", "笔试题目", "面试经验", "面试短评"];
    for (const kw of cutKeywords) {
      const idx = cleanText.indexOf(kw);
      if (idx !== -1) {
        cleanText = cleanText.substring(0, idx);
      }
    }
    cleanText = cleanText.replace(/立即申请/g, "").replace(/收藏/g, "").replace(/取消/g, "").replace(/确定/g, "");
    return cleanText.trim();
  }

  function getJdSemanticText() {
    const commonSelectors = [".job-sec-text", ".detail-content .job-sec .text", ".job-detail .text", ".job-detail-section .text", ".job-detail-content", ".detail-content", ".job-desc", ".job-description", ".job-detail-box", ".job-detail-box .text", ".job-sec .text", ".post-item__description", ".job-detail"];
    for (const sel of commonSelectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent.trim().length > 30) {
        return el.textContent.trim();
      }
    }
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

  function extractJobData() {
    const url = window.location.href;
    let title = "";
    let company = "";
    let salary = "";
    let location = "";
    let jd = "";

    if (url.includes("zhipin.com")) {
      title = (document.querySelector(".job-banner .name h1") || document.querySelector(".name h1") || document.querySelector(".job-title") || document.querySelector(".title-box h1") || {textContent: ""}).textContent.trim();
      company = (document.querySelector(".company-info a") || document.querySelector(".company-info .name") || document.querySelector(".company-text a") || document.querySelector(".company-name") || document.querySelector(".brand-name") || {textContent: ""}).textContent.trim();
      salary = (document.querySelector(".salary") || document.querySelector(".job-banner .salary") || document.querySelector(".salary-box .salary") || {textContent: ""}).textContent.trim();
      const locEl = document.querySelector(".job-banner .text") || document.querySelector(".info-primary .text-desc");
      if (locEl) {
        location = locEl.textContent.trim().split(" ")[0] || "";
      }
      const detailContainer = document.querySelector(".job-detail") || document.querySelector(".detail-content") || document.querySelector(".job-sec-text") || document.querySelector(".job-detail-section");
      if (detailContainer) {
        jd = detailContainer.innerText || detailContainer.textContent || "";
      }
    } else if (url.includes("nowcoder.com")) {
      title = (document.querySelector(".job-name") || document.querySelector(".jobs-name") || document.querySelector(".detail-title") || document.querySelector("h1") || {textContent: ""}).textContent.trim();
      company = (document.querySelector(".company-name") || document.querySelector(".company-title") || document.querySelector(".company-info") || {textContent: ""}).textContent.trim();
      salary = (document.querySelector(".job-salary") || document.querySelector(".salary") || document.querySelector(".jobs-salary") || {textContent: ""}).textContent.trim();
      location = (document.querySelector(".job-city") || document.querySelector(".city") || document.querySelector(".jobs-city") || {textContent: ""}).textContent.trim();
      const detailContainer = document.querySelector(".job-detail-content") || document.querySelector(".detail-content") || document.querySelector(".job-desc") || document.querySelector(".post-item__description");
      if (detailContainer) {
        jd = detailContainer.innerText || detailContainer.textContent || "";
      }
    }

    if (!jd || jd.length < 10) {
      jd = getJdSemanticText();
    }
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
      right: "24px",
      bottom: "20px",
      zIndex: "999999",
      background: isError ? "#f43f5e" : "#10b981",
      color: "#ffffff",
      padding: "12px 20px",
      borderRadius: "8px",
      boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.3)",
      fontSize: "13px",
      fontWeight: "600",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    });
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // Feedback display
  function showFeedback(host, res) {
    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed",
      right: "24px",
      bottom: "140px",
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
      lineHeight: "1.5",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    });

    const match = res.matchResult || {};
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
        ${match.reason || "分析已完成"}
      </div>
      <div style="display: flex; gap: 8px;">
        <button id="internpath-view-btn" style="flex: 1; padding: 6px; background: #334155; border: none; border-radius: 4px; color: #f8fafc; font-size: 12px; cursor: pointer;">查看工作台</button>
        <button id="internpath-close-btn" style="padding: 6px 12px; background: transparent; border: 1px solid #475569; border-radius: 4px; color: #94a3b8; font-size: 12px; cursor: pointer;">关闭</button>
      </div>
    `;

    document.body.appendChild(overlay);

    overlay.querySelector("#internpath-close-btn").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#internpath-view-btn").addEventListener("click", () => {
      window.open(host.replace("/api", ""));
      overlay.remove();
    });

    setTimeout(() => {
      if (document.body.contains(overlay)) overlay.remove();
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
      autofillBtn.innerHTML = `自动回填职位`;

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

      const headers = { "Content-Type": "application/json" };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      fetch(`${host}/api/jobs/import`, {
        method: "POST",
        headers: headers,
        credentials: "include",
        body: JSON.stringify(jobData)
      })
      .then(async response => {
        if (!response.ok) {
          let errMsg = `HTTP error ${response.status}`;
          try {
            const errData = await response.json();
            if (errData && errData.detail) {
              errMsg = errData.detail;
            }
          } catch (_) {}
          throw new Error(errMsg);
        }
        return response.json();
      })
      .then(res => {
        importBtn.innerHTML = `一键后台分析`;
        importBtn.disabled = false;
        importBtn.style.opacity = "1.0";
        showFeedback(host, res);
      })
      .catch(err => {
        console.error("[InternPath] Import failed:", err);
        importBtn.innerHTML = `一键后台分析`;
        importBtn.disabled = false;
        importBtn.style.opacity = "1.0";
        showToast("导入失败，请检查配置或确认后端服务已启动！", true);
      });
    });
  });

  // 3. SPA Auto check triggered autofill
  let lastJobUrl = "";
  let lastJobTitle = "";
  let lastJobCompany = "";

  function checkAndAutoTrigger() {
    try {
      const jobData = extractJobData();
      if (jobData && jobData.title !== "未知职位" && jobData.jd_text !== "无详情") {
        if (jobData.source_url !== lastJobUrl || jobData.title !== lastJobTitle || jobData.company !== lastJobCompany) {
          lastJobUrl = jobData.source_url;
          lastJobTitle = jobData.title;
          lastJobCompany = jobData.company;

          initialJobData = jobData;
          jdTextarea.value = jobData.jd_text;
          updateJobActionsVisibility();

          console.log("[InternPath] 检测到职位发生改变或加载完成，自动发起静默回填:", jobData.title);
          
          chrome.runtime.sendMessage({ action: "autofill", data: jobData, isAuto: true });
        }
      }
    } catch (e) {
      console.error("[InternPath] 自动检测回填执行异常:", e);
    }
  }

  setInterval(checkAndAutoTrigger, 1500);
})();
