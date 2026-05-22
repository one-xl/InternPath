import type { ProjectExperience } from "../../types/profile";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { TextArea } from "../ui/TextArea";

interface ProjectExperienceEditorProps {
  projects: ProjectExperience[];
  onChange: (projects: ProjectExperience[]) => void;
}

export function ProjectExperienceEditor({ projects, onChange }: ProjectExperienceEditorProps) {
  function patchProject(id: string, patch: Partial<ProjectExperience>) {
    onChange(projects.map((project) => (project.id === id ? { ...project, ...patch } : project)));
  }

  function addProject() {
    onChange([
      ...projects,
      {
        id: crypto.randomUUID(),
        name: "新项目",
        role: "",
        description: "",
        techStack: [],
        impact: "",
      },
    ]);
  }

  return (
    <Card title="项目经历" action={<Button type="button" onClick={addProject}>添加项目</Button>}>
      <div className="project-editor-list">
        {projects.map((project) => (
          <article key={project.id} className="project-editor-card">
            <div className="form-grid">
              <label className="field">
                <span>项目名</span>
                <input value={project.name} onChange={(event) => patchProject(project.id, { name: event.target.value })} />
              </label>
              <label className="field">
                <span>角色</span>
                <input value={project.role} onChange={(event) => patchProject(project.id, { role: event.target.value })} />
              </label>
            </div>
            <TextArea
              label="项目描述"
              value={project.description}
              rows={4}
              onChange={(event) => patchProject(project.id, { description: event.target.value })}
            />
            <label className="field">
              <span>技术栈（用逗号分隔）</span>
              <input
                value={project.techStack.join(", ")}
                onChange={(event) => patchProject(project.id, { techStack: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })}
              />
            </label>
            <label className="field">
              <span>结果 / 影响</span>
              <input value={project.impact} onChange={(event) => patchProject(project.id, { impact: event.target.value })} />
            </label>
            <Button type="button" variant="danger" onClick={() => onChange(projects.filter((item) => item.id !== project.id))}>
              删除项目
            </Button>
          </article>
        ))}
      </div>
    </Card>
  );
}
