// Chrome Extension Background Service Worker

// Listen for messages from content scripts or popups
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "autofill") {
    const jobData = message.data;
    const isAuto = !!message.isAuto;
    
    // Find InternPath tabs
    chrome.storage.local.get(["internpathHost"], (items) => {
      const host = items.internpathHost || "http://localhost:8787";
      let hostName = "";
      try {
        hostName = new URL(host).hostname;
      } catch (_) {}

      chrome.tabs.query({}, (tabs) => {
        const targetTab = tabs && tabs.find(tab => {
          if (!tab.url) return false;
          const u = tab.url.toLowerCase();
          const t = (tab.title || "").toLowerCase();
          
          const matchesTitle = t.includes("internpath") || t.includes("实习通");
          const matchesHost = hostName && u.includes(hostName.toLowerCase());
          
          if (matchesTitle) return true;
          if (matchesHost) return true;
          return false;
        });
        
        if (targetTab) {
          // Inject autofill script
          chrome.scripting.executeScript({
            target: { tabId: targetTab.id },
            func: (data, isAutoVal) => {
              const companyInput = document.querySelector("input[placeholder*='例如：Vercel']");
              const titleInput = document.querySelector("input[placeholder*='例如：前端实习生']");
              const linkInput = document.querySelector("input[placeholder*='可选，用于回溯来源']");
              const locationInput = document.querySelector("input[placeholder*='例如：北京 / 远程']");
              const jdTextarea = document.querySelector(".analysis-form textarea") || document.querySelector("textarea");

              // 自动检测回填时，如果用户当前表单不为空，则静默跳过，避免覆盖用户的数据
              if (isAutoVal) {
                const hasCompany = companyInput && companyInput.value.trim().length > 0;
                const hasTitle = titleInput && titleInput.value.trim().length > 0;
                if (hasCompany || hasTitle) {
                  return;
                }
              }

              function setReactValue(el, val) {
                if (!el) return;
                const lastValue = el.value;
                el.value = val;
                const event = new Event('input', { bubbles: true });
                const tracker = el._valueTracker;
                if (tracker) {
                  tracker.setValue(lastValue);
                }
                el.dispatchEvent(event);
              }

              if (companyInput) setReactValue(companyInput, data.company);
              if (titleInput) setReactValue(titleInput, data.title);
              if (linkInput) setReactValue(linkInput, data.source_url);
              if (locationInput) setReactValue(locationInput, data.location);
              if (jdTextarea) setReactValue(jdTextarea, data.jd_text);

              // 自动检测静默回填，工作台无需弹出通知横幅，不打扰用户
              if (isAutoVal) return;

              // Show toast feedback on the website
              const toast = document.createElement("div");
              Object.assign(toast.style, {
                position: "fixed",
                top: "24px",
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: "999999",
                background: "linear-gradient(135deg, #10b981, #059669)",
                color: "#ffffff",
                padding: "12px 24px",
                borderRadius: "8px",
                boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.3)",
                fontSize: "14px",
                fontWeight: "600",
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
              });
              toast.textContent = "🧭 InternPath: 岗位数据已自动回填成功！";
              document.body.appendChild(toast);
              setTimeout(() => toast.remove(), 3500);
            },
            args: [jobData, isAuto]
          }, () => {
            if (!isAuto) {
              // Focus the tab and window ONLY for manual triggers
              chrome.tabs.update(targetTab.id, { active: true });
              chrome.windows.update(targetTab.windowId, { focused: true });
            }
            sendResponse({ success: true });
          });
        } else {
          sendResponse({ success: false, error: "not_found" });
        }
      });
    });
    return true; // Keep message channel open for async sendResponse
  }
  
  if (message.action === "sync_session") {
    // Attempt to read token from the active website tab
    chrome.storage.local.get(["internpathHost"], (items) => {
      const host = items.internpathHost || "http://localhost:8787";
      let hostName = "";
      try {
        hostName = new URL(host).hostname;
      } catch (_) {}

      chrome.tabs.query({}, (tabs) => {
        const targetTabs = tabs && tabs.filter(tab => {
          if (!tab.url) return false;
          const u = tab.url.toLowerCase();
          const t = (tab.title || "").toLowerCase();
          
          const matchesTitle = t.includes("internpath") || t.includes("实习通");
          const matchesHost = hostName && u.includes(hostName.toLowerCase());
          
          return matchesTitle || matchesHost;
        });
        
        if (targetTabs && targetTabs.length > 0) {
          chrome.scripting.executeScript({
            target: { tabId: targetTabs[0].id },
            func: () => {
              return document.cookie;
            }
          }, (results) => {
            if (results && results[0]) {
              sendResponse({ success: true, cookies: results[0].result });
            } else {
              sendResponse({ success: false, error: "failed_to_execute" });
            }
          });
        } else {
          sendResponse({ success: false, error: "tab_not_found" });
        }
      });
    });
    return true;
  }

  if (message.action === "get_resumes") {
    chrome.storage.local.get(["internpathHost", "internpathToken"], (items) => {
      const host = items.internpathHost || "http://localhost:8787";
      const token = items.internpathToken || "";
      const headers = { "Content-Type": "application/json" };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      
      fetch(`${host}/api/resumes`, {
        method: "GET",
        headers: headers
      })
      .then(r => r.json())
      .then(res => sendResponse({ success: true, resumes: res.resumes || [] }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    });
    return true;
  }

  if (message.action === "tailor_fields") {
    chrome.storage.local.get(["internpathHost", "internpathToken"], (items) => {
      const host = items.internpathHost || "http://localhost:8787";
      const token = items.internpathToken || "";
      const headers = { "Content-Type": "application/json" };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      
      fetch(`${host}/api/analysis/tailor-form-fields`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(message.data)
      })
      .then(r => r.json())
      .then(res => {
        if (res.ok) {
          sendResponse({ success: true, tailored_data: res.tailored_data });
        } else {
          sendResponse({ success: false, error: res.detail || "AI提炼失败" });
        }
      })
      .catch(err => sendResponse({ success: false, error: err.message }));
    });
    return true;
  }
});
