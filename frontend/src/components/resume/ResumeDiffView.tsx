import React, { useState } from "react";

interface ModificationItem {
  section_name: string;
  section_index: number;
  original: string;
  new: string;
  reason: string;
}

interface ResumeDiffViewProps {
  modificationLog: ModificationItem[];
}

interface DiffCharPart {
  text: string;
  highlight: boolean;
}

interface DiffRow {
  type: "unchanged" | "deleted" | "added" | "modified";
  leftContent?: string;
  rightContent?: string;
  leftHighlights?: DiffCharPart[];
  rightHighlights?: DiffCharPart[];
}

// Custom LCS character diff algorithm
function diffChars(s1: string, s2: string): { left: DiffCharPart[]; right: DiffCharPart[] } {
  const n = s1.length;
  const m = s2.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (s1[i - 1] === s2[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  const leftParts: DiffCharPart[] = [];
  const rightParts: DiffCharPart[] = [];

  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && s1[i - 1] === s2[j - 1]) {
      leftParts.push({ text: s1[i - 1], highlight: false });
      rightParts.push({ text: s2[j - 1], highlight: false });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      rightParts.push({ text: s2[j - 1], highlight: true });
      j--;
    } else {
      leftParts.push({ text: s1[i - 1], highlight: true });
      i--;
    }
  }

  leftParts.reverse();
  rightParts.reverse();

  const merge = (parts: DiffCharPart[]): DiffCharPart[] => {
    const merged: DiffCharPart[] = [];
    for (const part of parts) {
      const last = merged[merged.length - 1];
      if (last && last.highlight === part.highlight) {
        last.text += part.text;
      } else {
        merged.push({ ...part });
      }
    }
    return merged;
  };

  return {
    left: merge(leftParts),
    right: merge(rightParts),
  };
}

// Custom LCS line diff algorithm
function diffLines(original: string, newStr: string): DiffRow[] {
  const normalize = (s: string) => s.replace(/\r\n/g, "\n");
  const leftLines = normalize(original).split("\n");
  const rightLines = normalize(newStr).split("\n");

  const n = leftLines.length;
  const m = rightLines.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (leftLines[i - 1] === rightLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  let i = n, j = m;
  const rawRows: Array<{ type: "unchanged" | "deleted" | "added"; left?: string; right?: string }> = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && leftLines[i - 1] === rightLines[j - 1]) {
      rawRows.push({ type: "unchanged", left: leftLines[i - 1], right: rightLines[j - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      rawRows.push({ type: "added", right: rightLines[j - 1] });
      j--;
    } else {
      rawRows.push({ type: "deleted", left: leftLines[i - 1] });
      i--;
    }
  }
  rawRows.reverse();

  const rows: DiffRow[] = [];
  let idx = 0;
  while (idx < rawRows.length) {
    const current = rawRows[idx];
    if (current.type === "deleted") {
      const deletions: string[] = [current.left!];
      let dPtr = idx + 1;
      while (dPtr < rawRows.length && rawRows[dPtr].type === "deleted") {
        deletions.push(rawRows[dPtr].left!);
        dPtr++;
      }

      const additions: string[] = [];
      let aPtr = dPtr;
      while (aPtr < rawRows.length && rawRows[aPtr].type === "added") {
        additions.push(rawRows[aPtr].right!);
        aPtr++;
      }

      if (additions.length > 0) {
        const pairCount = Math.min(deletions.length, additions.length);
        for (let p = 0; p < pairCount; p++) {
          const oLine = deletions[p];
          const nLine = additions[p];
          const charDiff = diffChars(oLine, nLine);
          rows.push({
            type: "modified",
            leftContent: oLine,
            rightContent: nLine,
            leftHighlights: charDiff.left,
            rightHighlights: charDiff.right,
          });
        }
        for (let d = pairCount; d < deletions.length; d++) {
          rows.push({
            type: "deleted",
            leftContent: deletions[d],
          });
        }
        for (let a = pairCount; a < additions.length; a++) {
          rows.push({
            type: "added",
            rightContent: additions[a],
          });
        }
        idx = aPtr;
      } else {
        for (const dLine of deletions) {
          rows.push({
            type: "deleted",
            leftContent: dLine,
          });
        }
        idx = dPtr;
      }
    } else if (current.type === "added") {
      rows.push({
        type: "added",
        rightContent: current.right!,
      });
      idx++;
    } else {
      rows.push({
        type: "unchanged",
        leftContent: current.left!,
        rightContent: current.right!,
      });
      idx++;
    }
  }

  return rows;
}

export function ResumeDiffView({ modificationLog }: ResumeDiffViewProps) {
  const [expandedCards, setExpandedCards] = useState<Record<number, boolean>>({});

  // Compute statistics
  let totalDeletedLines = 0;
  let totalAddedLines = 0;

  const cardDiffs = (modificationLog || []).map((item, index) => {
    const diffResult = diffLines(item.original || "", item.new || "");

    // Count stats for this card
    diffResult.forEach(row => {
      if (row.type === "deleted") {
        totalDeletedLines++;
      } else if (row.type === "added") {
        totalAddedLines++;
      } else if (row.type === "modified") {
        totalDeletedLines++;
        totalAddedLines++;
      }
    });

    return {
      item,
      diffResult,
      index,
    };
  });

  const toggleCard = (index: number) => {
    setExpandedCards((prev) => ({
      ...prev,
      [index]: prev[index] === false ? true : false, // Default is undefined (expanded), so if false -> true, else -> false
    }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "18px", width: "100%" }}>
      {/* Sleek CSS Injection for Transitions & Hovers */}
      <style>{`
        .diff-card-item {
          transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .diff-card-item:hover {
          transform: translateY(-2px);
          box-shadow: 0 10px 25px rgba(0, 0, 0, 0.05) !important;
          border-color: rgba(99, 102, 241, 0.3) !important;
        }
        .ios-pill-btn {
          transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .ios-pill-btn:hover {
          background: rgba(99, 102, 241, 0.08) !important;
          color: #6366f1 !important;
        }
        .diff-line-number-left {
          user-select: none;
          color: rgba(239, 68, 68, 0.4);
          margin-right: 8px;
          font-size: 11px;
        }
        .diff-line-number-right {
          user-select: none;
          color: rgba(16, 185, 129, 0.4);
          margin-right: 8px;
          font-size: 11px;
        }
      `}</style>

      {/* Modern iOS Pill Summary Banner */}
      <div
        style={{
          display: "flex",
          gap: "12px",
          alignItems: "center",
          flexWrap: "wrap",
          background: "var(--card-bg, #ffffff)",
          borderRadius: "16px",
          padding: "16px 20px",
          marginBottom: "8px",
          border: "1px solid var(--line, #e2e8f0)",
          boxShadow: "0 4px 20px rgba(0,0,0,0.015)",
        }}
      >
        <span
          style={{
            fontSize: "13px",
            fontWeight: "700",
            color: "#6366f1",
            background: "rgba(99, 102, 241, 0.08)",
            padding: "6px 12px",
            borderRadius: "999px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          📝 修改段落: {modificationLog.length} 个
        </span>
        <span
          style={{
            fontSize: "13px",
            fontWeight: "700",
            color: "#ef4444",
            background: "rgba(239, 68, 68, 0.08)",
            padding: "6px 12px",
            borderRadius: "999px",
            display: "flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          − {totalDeletedLines} 行删除
        </span>
        <span
          style={{
            fontSize: "13px",
            fontWeight: "700",
            color: "#10b981",
            background: "rgba(16, 185, 129, 0.08)",
            padding: "6px 12px",
            borderRadius: "999px",
            display: "flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          + {totalAddedLines} 行新增
        </span>
      </div>

      {/* Diff Cards List */}
      {cardDiffs.map(({ item, diffResult, index }) => {
        const isExpanded = expandedCards[index] !== false; // Default to true

        return (
          <div
            key={index}
            className="diff-card-item"
            style={{
              background: "var(--card-bg, #ffffff)",
              border: "1px solid var(--line, #e2e8f0)",
              borderRadius: "16px",
              boxShadow: "0 4px 15px rgba(0,0,0,0.01)",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* iOS Section Header */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "16px 20px",
                borderBottom: isExpanded ? "1px solid var(--line, #e2e8f0)" : "none",
                background: "var(--bg, #f8fafc)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center" }}>
                <span
                  style={{
                    display: "inline-block",
                    width: "4px",
                    height: "16px",
                    borderRadius: "2px",
                    background: "linear-gradient(to bottom, #6366f1, #a855f7)",
                    marginRight: "10px",
                  }}
                />
                <span style={{ fontWeight: "800", fontSize: "15px", color: "var(--text-main, #1e293b)" }}>
                  {item.section_name}
                </span>
              </div>
              <button
                onClick={() => toggleCard(index)}
                className="ios-pill-btn"
                style={{
                  background: "var(--bg, #f1f5f9)",
                  border: "none",
                  padding: "6px 12px",
                  borderRadius: "20px",
                  fontSize: "12px",
                  color: "var(--text-muted, #64748b)",
                  fontWeight: "700",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  outline: "none",
                }}
              >
                {isExpanded ? "收起 ▲" : "展开 ▼"}
              </button>
            </div>

            {isExpanded && (
              <>
                {/* Content columns header */}
                <div style={{ display: "flex", width: "100%", borderBottom: "1px solid var(--line, #e2e8f0)" }}>
                  <div
                    style={{
                      flex: 1,
                      padding: "10px 16px",
                      background: "rgba(239, 68, 68, 0.02)",
                      fontWeight: "700",
                      fontSize: "13px",
                      color: "#b91c1c",
                      borderRight: "1px solid var(--line, #e2e8f0)",
                    }}
                  >
                    修改前
                  </div>
                  <div
                    style={{
                      flex: 1,
                      padding: "10px 16px",
                      background: "rgba(16, 185, 129, 0.02)",
                      fontWeight: "700",
                      fontSize: "13px",
                      color: "#15803d",
                    }}
                  >
                    修改后
                  </div>
                </div>

                {/* Diff Lines Rendering */}
                <div style={{ display: "flex", flexDirection: "column", background: "#ffffff" }}>
                  {diffResult.map((row, rIdx) => {
                    const rowKey = `${index}-row-${rIdx}`;

                    if (row.type === "unchanged") {
                      return (
                        <div key={rowKey} style={{ display: "flex", width: "100%", borderBottom: "1px solid #f8fafc" }}>
                          {/* Left Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              color: "var(--text-muted, #64748b)",
                              borderRight: "1px solid var(--line, #e2e8f0)",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                            }}
                          >
                            {row.leftContent}
                          </div>
                          {/* Right Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              color: "var(--text-muted, #64748b)",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                            }}
                          >
                            {row.rightContent}
                          </div>
                        </div>
                      );
                    }

                    if (row.type === "deleted") {
                      return (
                        <div key={rowKey} style={{ display: "flex", width: "100%", borderBottom: "1px solid #f8fafc" }}>
                          {/* Left Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              background: "rgba(239, 68, 68, 0.06)",
                              color: "#dc2626",
                              borderRight: "1px solid var(--line, #e2e8f0)",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                              display: "flex",
                              alignItems: "flex-start",
                            }}
                          >
                            <span className="diff-line-number-left">−</span>
                            <span style={{ flex: 1 }}>{row.leftContent}</span>
                          </div>
                          {/* Right Column (empty placeholder) */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              background: "rgba(0, 0, 0, 0.005)",
                              borderRight: "none",
                            }}
                          />
                        </div>
                      );
                    }

                    if (row.type === "added") {
                      return (
                        <div key={rowKey} style={{ display: "flex", width: "100%", borderBottom: "1px solid #f8fafc" }}>
                          {/* Left Column (empty placeholder) */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              background: "rgba(0, 0, 0, 0.005)",
                              borderRight: "1px solid var(--line, #e2e8f0)",
                            }}
                          />
                          {/* Right Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              background: "rgba(16, 185, 129, 0.06)",
                              color: "#16a34a",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                              display: "flex",
                              alignItems: "flex-start",
                            }}
                          >
                            <span className="diff-line-number-right">+</span>
                            <span style={{ flex: 1 }}>{row.rightContent}</span>
                          </div>
                        </div>
                      );
                    }

                    if (row.type === "modified") {
                      return (
                        <div key={rowKey} style={{ display: "flex", width: "100%", borderBottom: "1px solid #f8fafc" }}>
                          {/* Left Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              background: "rgba(239, 68, 68, 0.06)",
                              color: "#dc2626",
                              borderRight: "1px solid var(--line, #e2e8f0)",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                              display: "flex",
                              alignItems: "flex-start",
                            }}
                          >
                            <span className="diff-line-number-left">−</span>
                            <span style={{ flex: 1 }}>
                              {row.leftHighlights?.map((part, pIdx) => (
                                <span
                                  key={pIdx}
                                  style={
                                    part.highlight
                                      ? { background: "rgba(239, 68, 68, 0.22)", color: "#991b1b", borderRadius: "3px", padding: "1px 2px", fontWeight: "600" }
                                      : {}
                                  }
                                >
                                  {part.text}
                                </span>
                              ))}
                            </span>
                          </div>
                          {/* Right Column */}
                          <div
                            style={{
                              flex: 1,
                              padding: "6px 16px",
                              fontFamily: 'var(--font-mono, "SF Mono", Monaco, Menlo, Consolas, monospace)',
                              fontSize: "13px",
                              background: "rgba(16, 185, 129, 0.06)",
                              color: "#16a34a",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-all",
                              lineHeight: "1.5",
                              display: "flex",
                              alignItems: "flex-start",
                            }}
                          >
                            <span className="diff-line-number-right">+</span>
                            <span style={{ flex: 1 }}>
                              {row.rightHighlights?.map((part, pIdx) => (
                                <span
                                  key={pIdx}
                                  style={
                                    part.highlight
                                      ? { background: "rgba(16, 185, 129, 0.22)", color: "#115e59", borderRadius: "3px", padding: "1px 2px", fontWeight: "600" }
                                      : {}
                                  }
                                >
                                  {part.text}
                                </span>
                              ))}
                            </span>
                          </div>
                        </div>
                      );
                    }

                    return null;
                  })}
                </div>

                {/* iOS Premium Left-border Reason Footer */}
                {item.reason && (
                  <div
                    style={{
                      display: "flex",
                      gap: "10px",
                      padding: "14px 20px",
                      background: "rgba(99, 102, 241, 0.015)",
                      borderTop: "1px solid var(--line, #e2e8f0)",
                      borderLeft: "4px solid #6366f1",
                    }}
                  >
                    <span style={{ fontSize: "15px" }}>💡</span>
                    <span style={{ fontSize: "13px", color: "var(--text-muted, #475569)", lineHeight: "1.6", fontWeight: "500" }}>
                      {item.reason}
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
