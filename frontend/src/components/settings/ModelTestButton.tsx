import type { ModelTestStatus } from "../../types/modelConfig";
import { Button } from "../ui/Button";

interface ModelTestButtonProps {
  status: ModelTestStatus;
  message?: string;
  diagnostics?: any;
  onTest: () => void;
}

export function ModelTestButton({ status, message, diagnostics, onTest }: ModelTestButtonProps) {
  const testing = status === "testing";
  return (
    <div className="model-test-container" style={{ display: "flex", flexDirection: "column", width: "100%" }}>
      <div className={`model-test model-test-${status}`} style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <Button type="button" variant="secondary" disabled={testing} onClick={onTest}>
          {testing ? "测试中..." : "测试连接"}
        </Button>
        {message && <span style={{ fontSize: "14px", color: status === "success" ? "#16a34a" : status === "failed" ? "#dc2626" : "inherit" }}>{message}</span>}
      </div>
      
      {(status === "failed" || status === "success") && diagnostics && (
        <details className="diagnostic-details" style={{
          marginTop: "12px",
          width: "100%",
          textAlign: "left",
          background: status === "success" ? "#f0fdf4" : "#fef2f2",
          border: status === "success" ? "1px solid #bbf7d0" : "1px solid #fca5a5",
          borderRadius: "6px",
          overflow: "hidden"
        }}>
          <summary style={{
            padding: "8px 12px",
            fontSize: "13px",
            fontWeight: "bold",
            color: status === "success" ? "#166534" : "#991b1b",
            cursor: "pointer",
            outline: "none",
            userSelect: "none"
          }}>
            {status === "success" ? "查看连通性与 Token 统计诊断信息" : "请求诊断与 Token 使用信息"} (点击展开/折叠)
          </summary>
          <div style={{
            padding: "12px",
            fontSize: "12px",
            background: "white",
            borderTop: status === "success" ? "1px solid #bbf7d0" : "1px solid #fca5a5",
            color: "#374151"
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "8px" }}>
              <tbody>
                <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "4px 0", fontWeight: "bold", width: "150px" }}>Provider:</td>
                  <td style={{ padding: "4px 0" }}>{diagnostics.provider}</td>
                </tr>
                {diagnostics.provider === "gemini" ? (
                  <>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Final Request URL:</td>
                      <td style={{ padding: "4px 0", wordBreak: "break-all" }}>{diagnostics.url || diagnostics.baseUrl || ""}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Model ID:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.modelId}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>generationConfig.temperature:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.temperature}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>generationConfig.maxOutputTokens:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.maxOutputTokens}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>generationConfig.responseMimeType:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.responseMimeType}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>是否传入 responseSchema:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.hasResponseSchema ? "是 (Yes)" : "否 (No)"}</td>
                    </tr>
                    {diagnostics.finishReason && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Finish Reason:</td>
                        <td style={{ padding: "4px 0", color: diagnostics.finishReason === "MAX_TOKENS" ? "#dc2626" : "inherit" }}>
                          <code>{diagnostics.finishReason}</code>
                        </td>
                      </tr>
                    )}
                    {diagnostics.promptTokenCount !== undefined && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Prompt Tokens:</td>
                        <td style={{ padding: "4px 0" }}>{diagnostics.promptTokenCount}</td>
                      </tr>
                    )}
                    {diagnostics.thoughtsTokenCount !== undefined && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Thoughts Tokens:</td>
                        <td style={{ padding: "4px 0", color: "#2563eb" }}>{diagnostics.thoughtsTokenCount}</td>
                      </tr>
                    )}
                    {diagnostics.candidatesTokenCount !== undefined && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Candidate Tokens:</td>
                        <td style={{ padding: "4px 0" }}>{diagnostics.candidatesTokenCount}</td>
                      </tr>
                    )}
                    {diagnostics.totalTokenCount !== undefined && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Total Tokens:</td>
                        <td style={{ padding: "4px 0" }}>{diagnostics.totalTokenCount}</td>
                      </tr>
                    )}
                    {diagnostics.thinkingLevel && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>Thinking Level:</td>
                        <td style={{ padding: "4px 0" }}><code>{diagnostics.thinkingLevel}</code></td>
                      </tr>
                    )}
                    {diagnostics.isTruncatedByMaxTokens !== undefined && (
                      <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "4px 0", fontWeight: "bold" }}>是否因为 MAX_TOKENS 被截断:</td>
                        <td style={{ padding: "4px 0", fontWeight: "bold", color: diagnostics.isTruncatedByMaxTokens ? "#dc2626" : "#16a34a" }}>
                          {diagnostics.isTruncatedByMaxTokens ? "是 (Yes)" : "否 (No)"}
                        </td>
                      </tr>
                    )}
                  </>
                ) : (
                  <>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>URL:</td>
                      <td style={{ padding: "4px 0", wordBreak: "break-all" }}>{diagnostics.baseUrl}{diagnostics.endpoint}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Model ID:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.modelId}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Input Shape:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.inputShape}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Encoding Format:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.encodingFormat}</td>
                    </tr>
                    <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "4px 0", fontWeight: "bold" }}>Dimensions:</td>
                      <td style={{ padding: "4px 0" }}>{diagnostics.dimensions ?? "默认 (1024)"}</td>
                    </tr>
                  </>
                )}
                {diagnostics.status !== undefined && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>HTTP Status:</td>
                    <td style={{ padding: "4px 0", color: status === "success" ? "#16a34a" : "#dc2626", fontWeight: "bold" }}>{diagnostics.status}</td>
                  </tr>
                )}
                {diagnostics.errorCode && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>Error Code:</td>
                    <td style={{ padding: "4px 0", color: "#dc2626" }}><code>{diagnostics.errorCode}</code></td>
                  </tr>
                )}
                {diagnostics.requestId && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>Request ID:</td>
                    <td style={{ padding: "4px 0" }}><code>{diagnostics.requestId}</code></td>
                  </tr>
                )}
                {diagnostics.errorType && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>错误类型:</td>
                    <td style={{ padding: "4px 0" }}>
                      {diagnostics.errorType === "high_demand" ? "模型高负载" : 
                       diagnostics.errorType === "auth" ? "鉴权失败" :
                       diagnostics.errorType === "not_found" ? "模型不存在" :
                       diagnostics.errorType === "rate_limit" ? "请求频次限制" :
                       diagnostics.errorType === "timeout" ? "请求超时" :
                       diagnostics.errorType === "invalid_request" ? "参数错误" :
                       diagnostics.errorType === "invalid_json" ? "返回非 JSON" :
                       diagnostics.errorType === "output_truncated_by_thinking" ? "输出被 Thinking 截断" :
                       diagnostics.errorType === "network" ? "网络错误" : diagnostics.errorType}
                    </td>
                  </tr>
                )}
                {diagnostics.retryable !== undefined && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>是否可重试:</td>
                    <td style={{ padding: "4px 0", fontWeight: "bold", color: diagnostics.retryable ? "#16a34a" : "#dc2626" }}>
                      {diagnostics.retryable ? "是" : "否"}
                    </td>
                  </tr>
                )}
                {diagnostics.fallbackUsed !== undefined && (
                  <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "4px 0", fontWeight: "bold" }}>使用备用模型:</td>
                    <td style={{ padding: "4px 0" }}>
                      {diagnostics.fallbackUsed ? `是 (已切换到: ${diagnostics.modelId})` : "否"}
                    </td>
                  </tr>
                )}
                <tr style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "4px 0", fontWeight: "bold" }}>Error Message:</td>
                  <td style={{ padding: "4px 0", color: status === "success" ? "#16a34a" : "#dc2626" }}>{diagnostics.message || "未知错误"}</td>
                </tr>
              </tbody>
            </table>

            {/* 1. Final Request Body Preview */}
            {diagnostics.rawRequestBody && (
              <div style={{ marginTop: "12px" }}>
                <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#4b5563" }}>Final Request Body Preview:</div>
                <pre style={{
                  margin: 0,
                  padding: "8px",
                  background: "#f9fafb",
                  border: "1px solid #e5e7eb",
                  borderRadius: "4px",
                  maxHeight: "150px",
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                  fontFamily: "monospace",
                  fontSize: "11px",
                  color: "#1f2937"
                }}>
                  {diagnostics.rawRequestBody}
                </pre>
              </div>
            )}

            {/* 2. Raw HTTP Response Preview */}
            <div style={{ marginTop: "12px" }}>
              <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#4b5563" }}>Raw HTTP Response Preview (前500字符):</div>
              <pre style={{
                margin: 0,
                padding: "8px",
                background: "#f9fafb",
                border: "1px solid #e5e7eb",
                borderRadius: "4px",
                maxHeight: "120px",
                overflowY: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                fontFamily: "monospace",
                fontSize: "11px",
                color: "#1f2937"
              }}>
                {diagnostics.rawResponseText || diagnostics.responsePreview || "(无内容)"}
              </pre>
            </div>

            {/* 3. Model Text Preview */}
            {diagnostics.modelText !== undefined && (
              <div style={{ marginTop: "12px" }}>
                <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#4b5563" }}>Model Text Preview (前500字符):</div>
                <pre style={{
                  margin: 0,
                  padding: "8px",
                  background: "#f9fafb",
                  border: "1px solid #e5e7eb",
                  borderRadius: "4px",
                  maxHeight: "120px",
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                  fontFamily: "monospace",
                  fontSize: "11px",
                  color: "#1f2937"
                }}>
                  {diagnostics.modelText || "(为空)"}
                </pre>
              </div>
            )}

            {/* 4. Parse Error */}
            {diagnostics.parseError && (
              <div style={{ marginTop: "12px" }}>
                <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#b91c1c" }}>Parse Error:</div>
                <pre style={{
                  margin: 0,
                  padding: "8px",
                  background: "#fdf2f2",
                  border: "1px solid #fecaca",
                  borderRadius: "4px",
                  maxHeight: "80px",
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                  fontFamily: "monospace",
                  fontSize: "11px",
                  color: "#991b1b"
                }}>
                  {diagnostics.parseError}
                </pre>
              </div>
            )}

            {/* Suggestions Card for thinking truncation */}
            {diagnostics.errorType === "output_truncated_by_thinking" && (
              <div style={{ marginTop: "12px", padding: "10px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", color: "#991b1b" }}>
                <div style={{ fontWeight: "bold", marginBottom: "4px", display: "flex", alignItems: "center", gap: "6px" }}>建议操作:</div>
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "11.5px", lineHeight: "1.6" }}>
                  <li>提高 <b>Max Output Tokens</b> (测试时会自动重试至 1024，建议配置主模型为 4096 或 8192)。</li>
                  <li>配置 <b>Thinking Level</b> 限制 (如 <code>minimal</code>)。</li>
                  <li>在高级配置中设置 <b>测试 Model ID (testModelId)</b> 为 <code>gemini-2.5-flash</code>，绕过 Preview 模型的测试连接。</li>
                </ul>
              </div>
            )}

            {/* 5. Suggestions Card for high load */}
            {diagnostics.errorType === "high_demand" && (
              <div style={{ marginTop: "12px", padding: "10px", background: "#fffbeb", border: "1px solid #fef3c7", borderRadius: "6px", color: "#b45309" }}>
                <div style={{ fontWeight: "bold", marginBottom: "4px", display: "flex", alignItems: "center", gap: "6px" }}>建议操作:</div>
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "11.5px", lineHeight: "1.6" }}>
                  <li>稍后重试</li>
                  <li>切换备用模型 (可在表单配置中设置 fallbackModelId)</li>
                  <li>降低请求频率</li>
                  <li>换用稳定版模型</li>
                </ul>
              </div>
            )}

            {/* 6. Fallback Recommendations */}
            <div style={{ marginTop: "12px", padding: "10px", background: "#ecfdf5", border: "1px solid #a7f3d0", borderRadius: "6px", color: "#065f46" }}>
              <div style={{ fontWeight: "bold", marginBottom: "4px", display: "flex", alignItems: "center", gap: "6px" }}>推荐备用模型 (建议在主模型繁忙或无法触发 JSON mode 时尝试):</div>
              <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "11.5px", lineHeight: "1.6" }}>
                <li><code>gemini-2.5-flash</code> (高性价比、高响应率与更佳 JSON 解析支持)</li>
                <li><code>gemini-flash-latest</code> (低延迟，高负载自适应高稳定版模型)</li>
              </ul>
            </div>
          </div>
        </details>
      )}
    </div>
  );
}
