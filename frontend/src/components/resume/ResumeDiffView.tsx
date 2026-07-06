import type { ReactNode } from "react";

interface ModificationItem {
  section_name: string;
  section_index: number;
  original: string;
  new: string;
  reason: string;
}

interface ResumeDiffViewProps {
  modificationLog: ModificationItem[];
  optimizedResumeMd?: string;
}

type DiffRowKind = "context" | "remove" | "add" | "skip";

interface DiffRow {
  kind: DiffRowKind;
  oldLine?: number;
  newLine?: number;
  text: string;
}

interface DiffStats {
  added: number;
  removed: number;
  changedSections: number;
}

function normalizeLineEndings(text: string): string {
  return (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function stripOptimizationSummary(markdown: string): string {
  const text = normalizeLineEndings(markdown).trimStart();
  const lines = text.split("\n");
  const firstLine = (lines[0] || "").replace(/^#+\s*/, "");
  if (!/摘要|summary/i.test(firstLine)) {
    return text;
  }

  const blankAfterBullet = lines.findIndex((line, index) => {
    if (index <= 1 || line.trim()) return false;
    const previousContent = [...lines.slice(1, index)].reverse().find((item) => item.trim());
    const nextContent = lines.slice(index + 1).find((item) => item.trim());
    return Boolean(previousContent?.trim().match(/^[-*]\s+/) && nextContent && !nextContent.trim().match(/^[-*]\s+/));
  });

  if (blankAfterBullet >= 0) {
    return lines.slice(blankAfterBullet + 1).join("\n").trimStart();
  }

  return text;
}

function splitLines(text: string): string[] {
  const normalized = normalizeLineEndings(text).trim();
  return normalized ? normalized.split("\n") : [];
}

function buildLineDiffRows(original: string, next: string): DiffRow[] {
  const left = splitLines(original);
  const right = splitLines(next);
  const dp = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0));

  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      dp[i][j] = left[i] === right[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      rows.push({ kind: "context", oldLine: i + 1, newLine: j + 1, text: left[i] });
      i += 1;
      j += 1;
    } else if (j >= right.length || (i < left.length && dp[i + 1][j] >= dp[i][j + 1])) {
      rows.push({ kind: "remove", oldLine: i + 1, text: left[i] });
      i += 1;
    } else {
      rows.push({ kind: "add", newLine: j + 1, text: right[j] });
      j += 1;
    }
  }
  return rows;
}

function compactRows(rows: DiffRow[], context = 2): DiffRow[] {
  const changedIndexes = rows
    .map((row, index) => (row.kind === "context" ? -1 : index))
    .filter((index) => index >= 0);
  if (!changedIndexes.length) return rows.slice(0, 12);

  const keep = new Set<number>();
  for (const index of changedIndexes) {
    for (let offset = -context; offset <= context; offset += 1) {
      const target = index + offset;
      if (target >= 0 && target < rows.length) keep.add(target);
    }
  }

  const compacted: DiffRow[] = [];
  let previousKept = -1;
  [...keep].sort((a, b) => a - b).forEach((index) => {
    if (previousKept >= 0 && index > previousKept + 1) {
      compacted.push({ kind: "skip", text: `${index - previousKept - 1} 行未修改` });
    }
    compacted.push(rows[index]);
    previousKept = index;
  });
  return compacted;
}

function tokenize(text: string): string[] {
  return normalizeLineEndings(text).match(/\s+|[A-Za-z0-9_./#+:-]+|./gu) || [];
}

function renderInlineDiff(text: string, peer: string, mode: "add" | "remove"): ReactNode {
  const source = tokenize(text);
  const target = tokenize(peer);
  const dp = Array.from({ length: source.length + 1 }, () => Array(target.length + 1).fill(0));
  for (let i = source.length - 1; i >= 0; i -= 1) {
    for (let j = target.length - 1; j >= 0; j -= 1) {
      dp[i][j] = source[i] === target[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const common = new Set<number>();
  let i = 0;
  let j = 0;
  while (i < source.length && j < target.length) {
    if (source[i] === target[j]) {
      common.add(i);
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i += 1;
    } else {
      j += 1;
    }
  }

  return source.map((token, index) => {
    if (common.has(index) || !token.trim()) return token;
    return mode === "add"
      ? <ins key={`${token}-${index}`}>{token}</ins>
      : <del key={`${token}-${index}`}>{token}</del>;
  });
}

function pairedPeer(rows: DiffRow[], index: number): string {
  const row = rows[index];
  if (row.kind === "remove" && rows[index + 1]?.kind === "add") return rows[index + 1].text;
  if (row.kind === "add" && rows[index - 1]?.kind === "remove") return rows[index - 1].text;
  return "";
}

function rowPrefix(kind: DiffRowKind): string {
  if (kind === "add") return "+";
  if (kind === "remove") return "-";
  if (kind === "skip") return "...";
  return " ";
}

function statsForItems(items: ModificationItem[]): DiffStats {
  return items.reduce<DiffStats>((stats, item) => {
    const rows = buildLineDiffRows(item.original || "", item.new || "");
    return {
      added: stats.added + rows.filter((row) => row.kind === "add").length,
      removed: stats.removed + rows.filter((row) => row.kind === "remove").length,
      changedSections: stats.changedSections + (rows.some((row) => row.kind !== "context") ? 1 : 0),
    };
  }, { added: 0, removed: 0, changedSections: 0 });
}

function DiffRows({ rows }: { rows: DiffRow[] }) {
  return (
    <div className="resume-diff-lines">
      {rows.map((row, index) => {
        const peer = pairedPeer(rows, index);
        return (
          <div key={`${row.kind}-${row.oldLine || ""}-${row.newLine || ""}-${index}`} className={`resume-diff-line is-${row.kind}`}>
            <span className="resume-diff-line-old">{row.oldLine || ""}</span>
            <span className="resume-diff-line-new">{row.newLine || ""}</span>
            <span className="resume-diff-line-prefix">{rowPrefix(row.kind)}</span>
            <code>
              {row.kind === "add" && peer ? renderInlineDiff(row.text, peer, "add") : null}
              {row.kind === "remove" && peer ? renderInlineDiff(row.text, peer, "remove") : null}
              {(row.kind !== "add" && row.kind !== "remove") || !peer ? row.text : null}
            </code>
          </div>
        );
      })}
    </div>
  );
}

export function ResumeDiffView({ modificationLog, optimizedResumeMd = "" }: ResumeDiffViewProps) {
  const resumeText = stripOptimizationSummary(optimizedResumeMd);
  const items = modificationLog || [];
  const stats = statsForItems(items);

  if (!resumeText.trim() && items.length === 0) {
    return <div className="agent-empty-row">暂无修改对照</div>;
  }

  return (
    <div className="resume-diff-full">
      <div className="resume-diff-meta" aria-label="修改标记说明">
        <span>精准修改对照</span>
        <em className="is-added">+ {stats.added} 行</em>
        <em className="is-deleted">- {stats.removed} 行</em>
        <em>{stats.changedSections} 处修改</em>
      </div>

      <article className="resume-diff-document">
        {items.length === 0 && <div className="agent-empty-row">暂无修改对照</div>}
        {items.map((item, index) => {
          const rows = compactRows(buildLineDiffRows(item.original || "", item.new || ""));
          return (
            <section key={`${item.section_name}-${item.section_index}-${index}`} className="resume-diff-change" aria-label={item.section_name}>
              <div className="resume-diff-section-title">
                <strong>{item.section_name || "修改段落"}</strong>
                <em>#{item.section_index}</em>
                {item.reason && <span>{item.reason}</span>}
              </div>
              <DiffRows rows={rows} />
            </section>
          );
        })}
      </article>
    </div>
  );
}
