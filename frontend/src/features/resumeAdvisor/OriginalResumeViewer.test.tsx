import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OriginalResumeViewer } from "./OriginalResumeViewer";

describe("OriginalResumeViewer", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("explains when the historic DOCX is unavailable and keeps the text locator usable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    render(
      <OriginalResumeViewer
        fileUrl="/api/agent/resume/sessions/session-1/resume-file"
        activeBlockId="block-1"
        preview={{
          sourceFormat: "docx",
          hasOriginalFile: true,
          inlinePreviewAvailable: false,
          locationNotice: "DOCX 支持浏览器预览和段落定位。",
        }}
        blocks={[
          {
            id: "block-1",
            order: 1,
            kind: "bullet",
            sectionId: "projects",
            sectionName: "项目经历",
            text: "负责简历分析页面开发",
            textHash: "hash-1",
            locationLabel: "项目经历 · 第 1 条",
            locatorConfidence: "high",
            locator: { sourceFormat: "docx" },
          },
        ]}
      />,
    );

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("该会话引用的原始 DOCX 已不再可供预览"));
    expect(screen.queryByRole("link", { name: "打开原始简历" })).not.toBeInTheDocument();
    expect(screen.getByText("定位文本")).toBeInTheDocument();
    expect(screen.getByText("负责简历分析页面开发")).toBeInTheDocument();
  });

  it("does not render the structured text a second time beside a working original preview", () => {
    render(
      <OriginalResumeViewer
        fileUrl="/api/agent/resume/sessions/session-1/resume-file"
        activeBlockId="block-1"
        preview={{
          sourceFormat: "pdf",
          hasOriginalFile: true,
          inlinePreviewAvailable: true,
          locationNotice: "PDF 位置来自原始页面文本坐标。",
        }}
        blocks={[
          {
            id: "block-1", order: 1, kind: "bullet", sectionId: "projects", sectionName: "项目经历",
            text: "负责简历分析页面开发", textHash: "hash-1", locationLabel: "项目经历 · 第 1 条",
            locatorConfidence: "high", locator: { sourceFormat: "pdf", pageNumber: 1 },
          },
          {
            id: "block-2", order: 2, kind: "bullet", sectionId: "projects", sectionName: "项目经历",
            text: "维护简历分析缓存", textHash: "hash-2", locationLabel: "项目经历 · 第 2 条",
            locatorConfidence: "high", locator: { sourceFormat: "pdf", pageNumber: 1 },
          },
        ]}
      />,
    );

    expect(screen.getByTitle("原始 PDF 简历预览")).toBeInTheDocument();
    expect(screen.queryByText("维护简历分析缓存")).not.toBeInTheDocument();
  });

  it("collapses duplicate locator paragraphs while keeping an aliased suggestion target visible", () => {
    render(
      <OriginalResumeViewer
        fileUrl=""
        activeBlockId="block-duplicate"
        preview={{
          sourceFormat: "docx",
          hasOriginalFile: false,
          inlinePreviewAvailable: false,
          locationNotice: "原始文件不可用，展示定位文本。",
        }}
        blocks={[
          {
            id: "block-primary", order: 1, kind: "bullet", sectionId: "project_experience", sectionName: "项目经历",
            text: "负责简历分析页面开发", textHash: "hash-1", locationLabel: "项目经历 · 第 1 条",
            locatorConfidence: "high", locator: { sourceFormat: "docx", paragraphIndex: 4 },
          },
          {
            id: "block-duplicate", order: 2, kind: "bullet", sectionId: "project_experience", sectionName: "项目经历",
            text: "负责简历分析页面开发", textHash: "hash-2", locationLabel: "项目经历 · 第 2 条",
            locatorConfidence: "high", locator: { sourceFormat: "docx", paragraphIndex: 8 },
          },
        ]}
      />,
    );

    expect(screen.getAllByText("负责简历分析页面开发")).toHaveLength(1);
    expect(screen.getByText("替换这里")).toBeInTheDocument();
  });
});
