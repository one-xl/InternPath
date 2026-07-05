import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import { reportLog } from "./services/apiClient";

window.addEventListener("error", (event) => {
  const msg = event.message || "Unknown error";
  const file = event.filename || "Unknown file";
  const line = event.lineno || 0;
  const col = event.colno || 0;
  const stack = event.error?.stack || "";
  reportLog("unhandled_js_error", `Message: ${msg} | File: ${file}:${line}:${col} | Stack: ${stack}`, "ERROR");
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  const detail = reason instanceof Error ? `${reason.message}\nStack: ${reason.stack}` : JSON.stringify(reason);
  reportLog("unhandled_promise_rejection", detail, "ERROR");
});

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
