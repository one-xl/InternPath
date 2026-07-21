import { useState, type ChangeEvent } from "react";

import type { ProjectKnowledgeDocument } from "../../types/projectKnowledge";

function projectDocuments(documents: ProjectKnowledgeDocument[]): ProjectKnowledgeDocument[] {
  const names = new Set<string>();
  return documents.filter((document) => {
    if (document.source_type !== "project") return false;
    const name = (document.file_name || document.title).trim().replace(/\s+/g, " ").toLocaleLowerCase();
    if (names.has(name)) return false;
    names.add(name);
    return true;
  });
}

interface ProjectKnowledgeSelectorProps {
  documents: ProjectKnowledgeDocument[];
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
  disabled?: boolean;
}

export function ProjectKnowledgeSelector({
  documents,
  selectedIds,
  onSelectionChange,
  disabled = false,
}: ProjectKnowledgeSelectorProps) {
  const projects = projectDocuments(documents);
  const selected = new Set(selectedIds);
  const allSelected = projects.length > 0 && projects.every((project) => selected.has(project.id));

  function toggleAll(event: ChangeEvent<HTMLInputElement>) {
    onSelectionChange(event.target.checked ? projects.map((project) => project.id) : []);
  }

  function toggleProject(projectId: number, checked: boolean) {
    const next = checked ? [...selected, projectId] : selectedIds.filter((id) => id !== projectId);
    onSelectionChange([...new Set(next)].filter((id) => projects.some((project) => project.id === id)));
  }

  if (!projects.length) {
    return <p className="project-knowledge-empty">还没有项目资料。上传 DOCX、PDF 或 TXT 后即可参与本次 RAG 检索。</p>;
  }

  return (
    <fieldset className="project-knowledge-selector" disabled={disabled}>
      <label className="project-knowledge-toggle project-knowledge-toggle--all">
        <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="全部项目" />
        <span>全部项目</span>
        <small>{projects.length} 份资料</small>
      </label>
      <div className="project-knowledge-list">
        {projects.map((project) => (
          <label key={project.id} className="project-knowledge-toggle">
            <input
              type="checkbox"
              checked={selected.has(project.id)}
              onChange={(event) => toggleProject(project.id, event.target.checked)}
              aria-label={project.title}
            />
            <span>{project.title}</span>
            <small>{project.chunk_count ? `${project.chunk_count} 个片段` : project.status || "已解析"}</small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface ProjectKnowledgePanelProps extends ProjectKnowledgeSelectorProps {
  isLoading: boolean;
  error?: string | null;
  uploadProgress?: { completed: number; total: number } | null;
  failedUploads?: Array<{ fileName: string; message: string }>;
  onUpload: (files: File[]) => void;
  onRetryFailedUploads?: () => void;
  onDeleteSelected: (documentIds: number[]) => void;
}

export function ProjectKnowledgePanel({
  documents,
  selectedIds,
  onSelectionChange,
  disabled,
  isLoading,
  error,
  uploadProgress = null,
  failedUploads = [],
  onUpload,
  onRetryFailedUploads,
  onDeleteSelected,
}: ProjectKnowledgePanelProps) {
  const projects = projectDocuments(documents);
  const selectedProjectIds = projects
    .filter((project) => selectedIds.includes(project.id))
    .map((project) => project.id);
  const [isExpanded, setIsExpanded] = useState(false);
  const uploadPercent = uploadProgress && uploadProgress.total
    ? Math.round((uploadProgress.completed / uploadProgress.total) * 100)
    : 0;

  return (
    <section className="project-knowledge-panel" aria-label="项目知识库">
      <button
        type="button"
        className="project-knowledge-panel__trigger"
        aria-expanded={isExpanded}
        title="管理项目资料：上传、选择检索范围或删除已选资料。展开后不会挤占对话区域。"
        onClick={() => setIsExpanded((current) => !current)}
      >
        <span className="project-knowledge-panel__trigger-title">项目资料库</span>
        <strong>{projects.length}</strong>
        <span className="project-knowledge-panel__trigger-action">{uploadProgress ? `上传中 ${uploadProgress.completed}/${uploadProgress.total}` : isExpanded ? "收起管理" : "管理资料"}</span>
      </button>
      {isExpanded && (
        <div className="project-knowledge-panel__drawer">
          <div className="project-knowledge-panel__head">
            <div>
              <h3>项目知识库</h3>
              <p>可批量上传项目资料，并选择全部或部分内容作为本次 JD 的检索范围。</p>
              <p className="project-knowledge-hint"><strong>提示：</strong>勾选的资料会参与下一次 RAG 检索；需要移除资料时，勾选后点击“删除已选”。</p>
            </div>
            <label className="btn btn-secondary project-knowledge-upload">
              批量上传资料
              <input
                type="file"
                accept=".docx,.pdf,.txt"
                multiple
                disabled={disabled || isLoading}
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  if (files.length) onUpload(files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
          </div>
          {uploadProgress && (
            <div className="project-knowledge-progress" role="progressbar" aria-valuemin={0} aria-valuemax={uploadProgress.total} aria-valuenow={uploadProgress.completed}>
              <div className="project-knowledge-progress__track"><span style={{ width: `${uploadPercent}%` }} /></div>
              <span>正在上传第 {Math.min(uploadProgress.completed + 1, uploadProgress.total)} / {uploadProgress.total} 份资料</span>
            </div>
          )}
          {error && <p className="project-knowledge-error">{error}</p>}
          {failedUploads.length > 0 && (
            <div className="project-knowledge-failures">
              <button type="button" className="btn btn-secondary" onClick={onRetryFailedUploads} disabled={disabled || isLoading}>
                重试失败文件（{failedUploads.length}）
              </button>
              <details>
                <summary>查看失败详情</summary>
                <ul>
                  {failedUploads.map((failure) => <li key={`${failure.fileName}-${failure.message}`}>{failure.fileName}：{failure.message}</li>)}
                </ul>
              </details>
            </div>
          )}
          {isLoading && !uploadProgress ? (
            <p className="project-knowledge-empty">正在加载项目知识库…</p>
          ) : (
            <>
          <ProjectKnowledgeSelector
            documents={projects}
            selectedIds={selectedIds}
            onSelectionChange={onSelectionChange}
            disabled={disabled || isLoading}
          />
          {projects.length > 0 && (
            <div className="project-knowledge-actions">
              <button
                type="button"
                className="project-knowledge-delete-selected"
                onClick={() => onDeleteSelected(selectedProjectIds)}
                disabled={disabled || isLoading || selectedProjectIds.length === 0}
              >
                删除已选（{selectedProjectIds.length}）
              </button>
            </div>
          )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
