import { useState } from "react";
import type { CandidateProfile } from "../../types/profile";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { TextArea } from "../ui/TextArea";
import { ProjectExperienceEditor } from "./ProjectExperienceEditor";
import { SkillTagEditor } from "./SkillTagEditor";

interface ProfileEditorProps {
  profile: CandidateProfile;
  savedAt: string;
  onSave: (profile: CandidateProfile) => void;
}

export function ProfileEditor({ profile, savedAt, onSave }: ProfileEditorProps) {
  const [draft, setDraft] = useState(profile);

  return (
    <div className="profile-editor">
      <Card title="基本求职目标" description="这些默认材料会参与每次新岗位分析。">
        <div className="form-grid">
          <label className="field">
            <span>目标岗位</span>
            <input value={draft.targetRole} onChange={(event) => setDraft({ ...draft, targetRole: event.target.value })} />
          </label>
          <label className="field">
            <span>教育经历</span>
            <input value={draft.education} onChange={(event) => setDraft({ ...draft, education: event.target.value })} />
          </label>
          <label className="field">
            <span>远程偏好</span>
            <select value={draft.remotePreference} onChange={(event) => setDraft({ ...draft, remotePreference: event.target.value as CandidateProfile["remotePreference"] })}>
              <option value="any">不限</option>
              <option value="remote">远程优先</option>
              <option value="hybrid">混合优先</option>
              <option value="onsite">现场可接受</option>
            </select>
          </label>
        </div>
        <TextArea
          label="当前简历文本"
          rows={9}
          value={draft.resumeText}
          onChange={(event) => setDraft({ ...draft, resumeText: event.target.value })}
        />
      </Card>
      <Card title="技能与偏好">
        <SkillTagEditor label="技能栈" values={draft.skillStack} onChange={(skillStack) => setDraft({ ...draft, skillStack })} />
        <SkillTagEditor label="偏好方向" values={draft.preferredDirections} onChange={(preferredDirections) => setDraft({ ...draft, preferredDirections })} />
        <SkillTagEditor label="不想投的方向" values={draft.blockedDirections} onChange={(blockedDirections) => setDraft({ ...draft, blockedDirections })} />
        <SkillTagEditor label="目标城市 / 地点偏好" values={draft.targetCities} onChange={(targetCities) => setDraft({ ...draft, targetCities })} />
      </Card>
      <ProjectExperienceEditor projects={draft.projects} onChange={(projects) => setDraft({ ...draft, projects })} />
      <div className="sticky-action">
        <Button variant="primary" onClick={() => onSave(draft)}>
          保存 Profile
        </Button>
        {savedAt ? <span className="save-note">已保存 {new Date(savedAt).toLocaleTimeString("zh-CN")}</span> : null}
      </div>
    </div>
  );
}
