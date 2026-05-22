import { useState } from "react";
import type { ResumeChunk } from "../../types/resume";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

interface ResumeChunkPreviewProps {
  chunks: ResumeChunk[];
  title?: string;
  description?: string;
  emptyText?: string;
}

export function ResumeChunkPreview({
  chunks,
  title = "本次分析参考的简历片段",
  description = "系统根据 JD 从你的简历中检索出最相关的经历片段，并基于这些内容生成投递决策和简历改造建议。",
  emptyText = "暂无检索片段。",
}: ResumeChunkPreviewProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <Card title={title} description={description}>
      {chunks.length === 0 ? (
        <p className="muted-line">{emptyText}</p>
      ) : (
        <div className="chunk-list">
          {chunks.map((chunk) => {
            const expanded = expandedId === chunk.id;
            return (
              <article className="chunk-card" key={chunk.id}>
                <button type="button" onClick={() => setExpandedId(expanded ? null : chunk.id)} aria-expanded={expanded}>
                  <span>
                    <strong>{chunk.section || "简历片段"}</strong>
                    <small>{chunk.metadata?.source || "上传简历"} · #{chunk.index + 1}</small>
                  </span>
                  <Badge tone="info">{Math.round(chunk.score ?? 0)}%</Badge>
                </button>
                <p>{expanded ? chunk.content : `${chunk.content.slice(0, 120)}${chunk.content.length > 120 ? "..." : ""}`}</p>
                {chunk.keywords?.length ? <div className="tag-row">{chunk.keywords.slice(0, 8).map((keyword) => <span key={keyword}>{keyword}</span>)}</div> : null}
              </article>
            );
          })}
        </div>
      )}
    </Card>
  );
}
