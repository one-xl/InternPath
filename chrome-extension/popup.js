document.addEventListener("DOMContentLoaded", () => {
  const hostInput = document.getElementById("host");
  const tokenInput = document.getElementById("token");
  const saveBtn = document.getElementById("save-btn");
  const statusDiv = document.getElementById("status");

  // Load saved configuration
  chrome.storage.local.get(["internpathHost", "internpathToken"], (items) => {
    if (items.internpathHost) {
      hostInput.value = items.internpathHost;
    }
    if (items.internpathToken) {
      tokenInput.value = items.internpathToken;
    }
  });

  saveBtn.addEventListener("click", () => {
    let host = hostInput.value.trim().replace(/\/$/, "");
    if (!host) {
      host = "http://localhost:8787";
    }
    const token = tokenInput.value.trim();

    chrome.storage.local.set(
      {
        internpathHost: host,
        internpathToken: token,
      },
      () => {
        statusDiv.className = "status success";
        statusDiv.textContent = "Configuration saved successfully!";
        setTimeout(() => {
          statusDiv.textContent = "";
        }, 2000);
      }
    );
  });
});
