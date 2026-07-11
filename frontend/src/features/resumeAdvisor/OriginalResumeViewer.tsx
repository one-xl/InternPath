import { useEffect, useMemo, useRef, useState } from "react";
import type { ResumeBlock, ResumePreview } from "./types";

type DocxPreviewError = { message: string; status?: number };

function docxPreviewFailureMessage(status?: number): DocxPreviewError {
  if (status === 401 || status === 403) return { status, message: "登录状态已失效，刷新页面或重新登录后可再次预览原始 DOCX。定位文本仍可用于找到需要修改的段落。" };
  if (status === 404) return { status, message: "该会话引用的原始 DOCX 已不再可供预览。你仍可使用下方定位文本找到需要修改的段落。" };
  if (status) return { status, message: "原始 DOCX 暂时无法加载。你仍可使用下方定位文本找到需要修改的段落，或稍后重试。" };
  return { message: "此 DOCX 无法在浏览器中完成预览，不影响建议和定位文本的使用。可打开原始简历查看完整排版。" };
}

function locatorTextKey(block: ResumeBlock): string {
  return [
    block.kind,
    block.sectionId || block.sectionName,
    block.text.replace(/\s+/g, "").toLocaleLowerCase(),
  ].join("|");
}

function deduplicateLocatorBlocks(blocks: ResumeBlock[]): ResumeBlock[] {
  const canonical: ResumeBlock[] = [];
  const indexByKey = new Map<string, number>();
  for (const block of blocks) {
    const key = locatorTextKey(block);
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      canonical.push({ ...block, legacyBlockIds: [...(block.legacyBlockIds || [])] });
      indexByKey.set(key, canonical.length - 1);
      continue;
    }
    const existing = canonical[existingIndex];
    const aliases = new Set([...(existing.legacyBlockIds || []), ...(block.legacyBlockIds || []), block.id]);
    canonical[existingIndex] = { ...existing, legacyBlockIds: [...aliases].filter((id) => id !== existing.id) };
  }
  return canonical;
}

export function OriginalResumeViewer({
  blocks,
  activeBlockId,
  preview,
  fileUrl,
}: {
  blocks: ResumeBlock[];
  activeBlockId: string | null;
  preview: ResumePreview | null;
  fileUrl: string;
}) {
  const activeRef = useRef<HTMLElement | null>(null);
  const docxPreviewRef = useRef<HTMLDivElement | null>(null);
  const [docxPreviewError, setDocxPreviewError] = useState<DocxPreviewError | null>(null);
  const visibleBlocks = useMemo(() => deduplicateLocatorBlocks(blocks), [blocks]);
  const activeBlock = visibleBlocks.find((block) => block.id === activeBlockId || block.legacyBlockIds?.includes(activeBlockId || ""))
    ?? blocks.find((block) => block.id === activeBlockId);
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [activeBlock?.id]);

  useEffect(() => {
    setDocxPreviewError(null);
    if (preview?.sourceFormat !== "docx" || !fileUrl || !docxPreviewRef.current) return;
    const controller = new AbortController();
    const container = docxPreviewRef.current;
    container.replaceChildren();
    void fetch(fileUrl, { credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        const { renderAsync } = await import("docx-preview");
        await renderAsync(await response.arrayBuffer(), container, undefined, {
          inWrapper: false,
          ignoreWidth: false,
          ignoreHeight: false,
          renderHeaders: true,
          renderFooters: true,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = error instanceof Error && /^\d{3}$/.test(error.message) ? Number(error.message) : undefined;
        setDocxPreviewError(docxPreviewFailureMessage(status));
      });
    return () => controller.abort();
  }, [fileUrl, preview?.sourceFormat]);

  const showLocatorText = !preview?.hasOriginalFile
    || Boolean(docxPreviewError)
    || (!preview.inlinePreviewAvailable && preview.sourceFormat !== "docx");
  return (
    <aside className="resume-advisor-viewer" aria-label="原始简历定位">
      <h2>原简历定位</h2>
      {preview?.hasOriginalFile && docxPreviewError?.status !== 404 && <a className="resume-advisor-original-file" href={`${fileUrl}${activeBlock?.locator.pageNumber ? `#page=${activeBlock.locator.pageNumber}` : ""}`} target="_blank" rel="noreferrer">打开原始简历</a>}
      {activeBlock && <p className="resume-advisor-location">替换这里：{activeBlock.locationLabel}{activeBlock.locatorConfidence === "approximate" ? "（近似定位）" : ""}</p>}
      {preview && <p className="muted">{preview.locationNotice}</p>}
      {preview?.inlinePreviewAvailable && fileUrl && <iframe className="resume-advisor-pdf-preview" title="原始 PDF 简历预览" src={`${fileUrl}${activeBlock?.locator.pageNumber ? `#page=${activeBlock.locator.pageNumber}` : ""}`} />}
      {preview?.sourceFormat === "docx" && preview.hasOriginalFile && <div className="resume-advisor-docx-preview" ref={docxPreviewRef} hidden={Boolean(docxPreviewError)} />}
      {docxPreviewError && <p className="resume-advisor-warning" role="status"><strong>已切换为定位文本。</strong>{docxPreviewError.message}</p>}
      {showLocatorText && preview?.sourceFormat === "docx" && <h3 className="resume-advisor-locator-heading">定位文本</h3>}
      {showLocatorText && visibleBlocks.map((block) => (
        <article
          key={block.id}
          ref={(element) => { if (block.id === activeBlock?.id) activeRef.current = element; }}
          className={`resume-advisor-block ${block.id === activeBlock?.id ? "highlighted" : ""}`}
        >
          {block.id === activeBlock?.id && <span className="resume-advisor-replace-label">替换这里</span>}
          <p className={block.kind === "heading" ? "heading" : ""}>{block.text}</p>
        </article>
      ))}
      {showLocatorText && !visibleBlocks.length && <p className="muted">选择会话后显示其不可变简历快照。</p>}
    </aside>
  );
}
