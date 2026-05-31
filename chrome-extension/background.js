// Chrome Extension Background Service Worker

// Listen for messages from content scripts or popups
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "autofill") {
    const jobData = message.data;
    
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
          
          const matchesHost = hostName && u.includes(hostName.toLowerCase());
          const matchesLocal = u.includes("localhost") || u.includes("127.0.0.1");
          const matchesTitle = t.includes("internpath") || t.includes("实习通");
          
          return matchesHost || matchesLocal || matchesTitle;
        });
        
        if (targetTab) {
          // Inject autofill script
          chrome.scripting.executeScript({
            target: { tabId: targetTab.id },
            func: (data) => {
              const companyInput = document.querySelector("input[placeholder*='例如：Vercel']");
              const titleInput = document.querySelector("input[placeholder*='例如：前端实习生']");
              const linkInput = document.querySelector("input[placeholder*='可选，用于回溯来源']");
              const locationInput = document.querySelector("input[placeholder*='例如：北京 / 远程']");
              const jdTextarea = document.querySelector(".analysis-form textarea") || document.querySelector("textarea");

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
            args: [jobData]
          }, () => {
            // Focus the tab and window
            chrome.tabs.update(targetTab.id, { active: true });
            chrome.windows.update(targetTab.windowId, { focused: true });
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
          
          const matchesHost = hostName && u.includes(hostName.toLowerCase());
          const matchesLocal = u.includes("localhost") || u.includes("127.0.0.1");
          const matchesTitle = t.includes("internpath") || t.includes("实习通");
          
          return matchesHost || matchesLocal || matchesTitle;
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
});
