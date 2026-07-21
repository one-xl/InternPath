import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectKnowledgePanel, ProjectKnowledgeSelector } from "./ProjectKnowledgeSelector";

afterEach(cleanup);

const documents = [
  { id: 41, title: "Payment platform", source_type: "project" },
  { id: 57, title: "Data pipeline", source_type: "project" },
  { id: 99, title: "Current resume", source_type: "resume" },
];

describe("ProjectKnowledgeSelector", () => {
  it("selects all project knowledge documents without submitting non-project materials", () => {
    const onSelectionChange = vi.fn();

    render(
      <ProjectKnowledgeSelector
        documents={documents}
        selectedIds={[]}
        onSelectionChange={onSelectionChange}
      />,
    );

    expect(screen.queryByText("Current resume")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("全部项目"));

    expect(onSelectionChange).toHaveBeenLastCalledWith([41, 57]);
  });

  it("submits only the remaining selected project IDs after deselecting one", () => {
    const onSelectionChange = vi.fn();
    const { rerender } = render(
      <ProjectKnowledgeSelector
        documents={documents}
        selectedIds={[41, 57]}
        onSelectionChange={onSelectionChange}
      />,
    );

    fireEvent.click(screen.getByLabelText("Payment platform"));
    expect(onSelectionChange).toHaveBeenLastCalledWith([57]);

    rerender(
      <ProjectKnowledgeSelector
        documents={documents}
        selectedIds={[57]}
        onSelectionChange={onSelectionChange}
      />,
    );

    expect(screen.getByLabelText("Data pipeline")).toBeChecked();
    expect(screen.getByLabelText("Payment platform")).not.toBeChecked();
  });

  it("shows only one project when historical records share a file name", () => {
    render(
      <ProjectKnowledgeSelector
        documents={[
          { id: 1, title: "Latest payment platform", file_name: "payment.docx", source_type: "project" },
          { id: 2, title: "Older payment platform", file_name: "payment.docx", source_type: "project" },
        ]}
        selectedIds={[1, 2]}
        onSelectionChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Latest payment platform")).toBeInTheDocument();
    expect(screen.queryByLabelText("Older payment platform")).not.toBeInTheDocument();
  });

  it("accepts multiple project files in a single upload selection", () => {
    const onUpload = vi.fn();
    const { container } = render(
      <ProjectKnowledgePanel
        documents={documents}
        selectedIds={[]}
        onSelectionChange={vi.fn()}
        isLoading={false}
        onUpload={onUpload}
        onDeleteSelected={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /项目资料/ }));
    const input = container.querySelector('input[type="file"]');
    const firstFile = new File(["payment"], "payment-platform.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const secondFile = new File(["pipeline"], "data-pipeline.txt", { type: "text/plain" });

    expect(input).toHaveAttribute("multiple");
    expect(screen.getByText(/勾选的资料会参与下一次 RAG 检索/)).toBeInTheDocument();
    fireEvent.change(input!, { target: { files: [firstFile, secondFile] } });

    expect(onUpload).toHaveBeenCalledWith([firstFile, secondFile]);
  });

  it("keeps failed files available for one-click retry and exposes upload progress", () => {
    const onRetryFailedUploads = vi.fn();
    render(
      <ProjectKnowledgePanel
        documents={documents}
        selectedIds={[]}
        onSelectionChange={vi.fn()}
        isLoading={false}
        uploadProgress={{ completed: 2, total: 5 }}
        failedUploads={[{ fileName: "failed.docx", message: "deadlock detected" }]}
        onUpload={vi.fn()}
        onRetryFailedUploads={onRetryFailedUploads}
        onDeleteSelected={vi.fn()}
      />,
    );

    expect(screen.queryByText("重试失败文件（1）")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /项目资料/ }));

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
    fireEvent.click(screen.getByRole("button", { name: "重试失败文件（1）" }));
    expect(onRetryFailedUploads).toHaveBeenCalledOnce();
  });

  it("deletes the selected project documents from the knowledge drawer", () => {
    const onDeleteSelected = vi.fn();
    render(
      <ProjectKnowledgePanel
        documents={documents}
        selectedIds={[41]}
        onSelectionChange={vi.fn()}
        isLoading={false}
        onUpload={vi.fn()}
        onDeleteSelected={onDeleteSelected}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /项目资料/ }));
    fireEvent.click(screen.getByRole("button", { name: "删除已选（1）" }));

    expect(onDeleteSelected).toHaveBeenCalledWith([41]);
  });
});
