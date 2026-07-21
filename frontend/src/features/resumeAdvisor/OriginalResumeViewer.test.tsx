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

  it("orders locator text by persisted resume order and keeps each source heading with its section", () => {
    const { container } = render(
      <OriginalResumeViewer
        fileUrl=""
        activeBlockId={null}
        preview={{
          sourceFormat: "docx",
          hasOriginalFile: false,
          inlinePreviewAvailable: false,
          locationNotice: "原始文件不可用，展示定位文本。",
        }}
        blocks={[
          {
            id: "project-content", order: 3, kind: "bullet", sectionId: "project_experience", sectionUid: "projects", sectionName: "项目经历",
            text: "InternPath 负责接口开发", textHash: "hash-project-content", locationLabel: "项目经历 · 第 1 条",
            locatorConfidence: "high", locator: { sourceFormat: "docx", layoutY: 300 },
          },
          {
            id: "education-content", order: 1, kind: "paragraph", sectionId: "education", sectionUid: "education", sectionName: "教育经历",
            text: "暨南大学 软件工程", textHash: "hash-education-content", locationLabel: "教育经历 · 第 1 条",
            locatorConfidence: "high", locator: { sourceFormat: "docx", layoutY: 100 },
          },
          {
            id: "project-heading", order: 2, kind: "heading", sectionId: "project_experience", sectionUid: "projects", sectionName: "项目经历",
            text: "项目经历", textHash: "hash-project-heading", locationLabel: "项目经历 · 标题",
            locatorConfidence: "high", locator: { sourceFormat: "docx", layoutY: 200 },
          },
          {
            id: "education-heading", order: 0, kind: "heading", sectionId: "education", sectionUid: "education", sectionName: "教育经历",
            text: "教育背景", textHash: "hash-education-heading", locationLabel: "教育经历 · 标题",
            locatorConfidence: "high", locator: { sourceFormat: "docx", layoutY: 0 },
          },
        ]}
      />,
    );

    expect(screen.getByLabelText("教育经历定位文本")).toHaveTextContent("教育背景暨南大学 软件工程");
    expect(screen.getByLabelText("项目经历定位文本")).toHaveTextContent("项目经历InternPath 负责接口开发");
    const content = container.textContent || "";
    expect(content.indexOf("教育背景")).toBeLessThan(content.indexOf("项目经历"));
    expect(content.indexOf("项目经历")).toBeLessThan(content.indexOf("InternPath 负责接口开发"));
  });
});
