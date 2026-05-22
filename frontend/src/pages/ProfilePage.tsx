import type { CandidateProfile } from "../types/profile";
import { ProfileEditor } from "../components/profile/ProfileEditor";

interface ProfilePageProps {
  profile: CandidateProfile;
  savedAt: string;
  onSave: (profile: CandidateProfile) => void;
}

export function ProfilePage({ profile, savedAt, onSave }: ProfilePageProps) {
  return (
    <div className="page-stack">
      <div className="page-title">
        <span className="section-kicker">个人材料库 / Profile</span>
        <h2>把默认材料维护好，后续每次判断都会更准。</h2>
        <p>这里不是简历编辑器，而是你的长期求职上下文。</p>
      </div>
      <ProfileEditor profile={profile} savedAt={savedAt} onSave={onSave} />
    </div>
  );
}
