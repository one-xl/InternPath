document.addEventListener("DOMContentLoaded", () => {
  const hostInput = document.getElementById("host");
  const emailInput = document.getElementById("email");
  const passwordInput = document.getElementById("password");
  
  const loggedOutPanel = document.getElementById("logged-out-panel");
  const loggedInPanel = document.getElementById("logged-in-panel");
  const userEmailSpan = document.getElementById("user-email");
  
  const loginBtn = document.getElementById("login-btn");
  const saveBtn = document.getElementById("save-btn");
  const logoutBtn = document.getElementById("logout-btn");
  const statusDiv = document.getElementById("status");

  // 1. 初始化加载配置
  chrome.storage.local.get(["internpathHost", "internpathToken", "internpathEmail"], (items) => {
    if (items.internpathHost) {
      hostInput.value = items.internpathHost;
    } else {
      hostInput.value = "http://localhost:8787";
    }
    
    if (items.internpathToken) {
      showLoggedIn(items.internpathEmail);
    } else {
      showLoggedOut();
    }
  });

  // 切换为已登录界面
  function showLoggedIn(email) {
    loggedOutPanel.style.display = "none";
    loggedInPanel.style.display = "block";
    userEmailSpan.textContent = email || "已登录账号";
  }

  // 切换为未登录界面
  function showLoggedOut() {
    loggedOutPanel.style.display = "block";
    loggedInPanel.style.display = "none";
    userEmailSpan.textContent = "-";
    if (emailInput) emailInput.value = "";
    if (passwordInput) passwordInput.value = "";
  }

  // 2. 登录按钮点击事件
  loginBtn.addEventListener("click", () => {
    let host = hostInput.value.trim().replace(/\/$/, "");
    if (!host) {
      host = "http://localhost:8787";
      hostInput.value = host;
    }
    const email = emailInput.value.trim();
    const password = passwordInput.value;

    if (!email || !password) {
      showStatus("请输入邮箱和密码", "error");
      return;
    }

    loginBtn.disabled = true;
    loginBtn.textContent = "登录中...";
    showStatus("正在连接服务器...", "info");

    fetch(`${host}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: email,
        password: password
      })
    })
    .then(async (response) => {
      if (!response.ok) {
        let errMsg = "登录失败";
        try {
          const errData = await response.json();
          errMsg = errData.detail || errMsg;
        } catch (_) {}
        throw new Error(errMsg);
      }
      return response.json();
    })
    .then((res) => {
      const token = res.token;
      if (!token) {
        throw new Error("服务器未返回有效的 Token");
      }
      // 保存至 storage
      chrome.storage.local.set({
        internpathHost: host,
        internpathToken: token,
        internpathEmail: email
      }, () => {
        loginBtn.disabled = false;
        loginBtn.textContent = "立即登录";
        showLoggedIn(email);
        showStatus("登录并保存成功！", "success");
      });
    })
    .catch((err) => {
      loginBtn.disabled = false;
      loginBtn.textContent = "立即登录";
      showStatus(err.message, "error");
    });
  });

  // 3. 更新地址按钮点击事件
  saveBtn.addEventListener("click", () => {
    let host = hostInput.value.trim().replace(/\/$/, "");
    if (!host) {
      host = "http://localhost:8787";
      hostInput.value = host;
    }
    chrome.storage.local.set({ internpathHost: host }, () => {
      showStatus("API 地址更新成功！", "success");
    });
  });

  // 4. 退出登录点击事件
  logoutBtn.addEventListener("click", () => {
    // 清理本地数据
    chrome.storage.local.remove(["internpathToken", "internpathEmail"], () => {
      showLoggedOut();
      showStatus("已退出登录", "success");
    });
  });

  // 显示提示状态
  function showStatus(msg, type) {
    statusDiv.textContent = msg;
    statusDiv.className = `status ${type}`;
    if (type === "success" || type === "error") {
      setTimeout(() => {
        if (statusDiv.textContent === msg) {
          statusDiv.textContent = "";
          statusDiv.className = "status";
        }
      }, 3000);
    }
  }
});
