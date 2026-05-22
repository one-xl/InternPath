import { useState } from "react";

interface AnalysisDebugPanelProps {
  jdText: string;
  hasParsedResume: boolean;
  chunksCount: number;
  activeEmbeddingConfig?: {
    provider: string;
    modelId: string;
    endpoint?: string;
  } | null;
  activeChatConfig?: {
    provider: string;
    modelId: string;
  } | null;
  analysisStatus: string;
  isAnalyzing: boolean;
  lastError?: string | null;
}

export function AnalysisDebugPanel({
  jdText,
  hasParsedResume,
  chunksCount,
  activeEmbeddingConfig,
  activeChatConfig,
  analysisStatus,
  isAnalyzing,
  lastError,
}: AnalysisDebugPanelProps) {
  const [isOpen, setIsOpen] = useState(false);

  const jdWordCount = jdText?.trim().length ?? 0;

  return (
    <div className="analysis-debug-panel">
      <details
        onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary>
          <div className="debug-summary-main">
            <span>RAG 求职分析调试面板 (Debug Panel)</span>
            <span className={`debug-runtime-pill ${isAnalyzing ? "running" : ""}`}>
              {isAnalyzing ? "正在运行中" : "空闲"}
            </span>
          </div>
          <span className="debug-summary-toggle">{isOpen ? "收起" : "展开"}</span>
        </summary>

        <div className="debug-panel-body">
          <div className="debug-panel-grid">
            <div className="debug-panel-block">
              <div className="debug-panel-title">输入与简历状态</div>
              <div>
                <span>岗位 JD:</span>
                <strong className={jdWordCount >= 80 ? "text-success" : "text-danger"}>
                  {jdWordCount > 0 ? `已输入 (${jdWordCount} 字)` : "未输入"}
                </strong>
              </div>
              <div>
                <span>简历状态:</span>
                <strong className={hasParsedResume ? "text-success" : "text-danger"}>
                  {hasParsedResume ? "已解析" : "未就绪"}
                </strong>
              </div>
              <div>
                <span>简历分段数 (Chunks):</span>
                <strong>{chunksCount} 段</strong>
              </div>
            </div>

            <div className="debug-panel-block">
              <div className="debug-panel-title">双模型配置</div>
              <div>
                <span>向量 Provider:</span>
                <strong>{activeEmbeddingConfig?.provider ?? "未配置"}</strong>
              </div>
              <div>
                <span>向量 Model ID:</span>
                <strong>{activeEmbeddingConfig?.modelId ?? "未配置"}</strong>
              </div>
              <div>
                <span>向量 Endpoint:</span>
                <strong>{activeEmbeddingConfig?.endpoint ?? "默认 (/embeddings/multimodal)"}</strong>
              </div>
              <div>
                <span>Gemini Model ID:</span>
                <strong>{activeChatConfig?.modelId ?? "未配置"}</strong>
              </div>
            </div>

            <div className="debug-panel-block">
              <div className="debug-panel-title">运行期状态机</div>
              <div>
                <span>核心状态 (Status):</span>
                <strong className={analysisStatus === "success" ? "text-success" : analysisStatus === "failed" ? "text-danger" : "text-warning"}>
                  {analysisStatus}
                </strong>
              </div>
              <div>
                <span>加载状态 (Analyzing):</span>
                <strong>{isAnalyzing ? "TRUE" : "FALSE"}</strong>
              </div>
              <div>
                <span>最近报错信息:</span>
                <strong className="debug-ellipsis text-danger" title={lastError ?? ""}>
                  {lastError ?? "无"}
                </strong>
              </div>
            </div>
          </div>

          {lastError && (
            <div className="debug-error-message">
              <strong>最近一次错误堆栈/信息:</strong> {lastError}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
