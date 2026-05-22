import { useEffect, useState } from "react";
import type { CandidateProfile } from "../types/profile";
import { loadFromStorage, saveToStorage } from "../utils/storage";

const PROFILE_KEY = "internpath.profile.v2";

const defaultProfile: CandidateProfile = {
  targetRole: "前端 / 全栈实习",
  resumeText: "熟悉 React、TypeScript、Python、SQL，做过个人工具、数据看板和 AI 辅助分析项目。",
  skillStack: ["React", "TypeScript", "JavaScript", "Python", "SQL"],
  projects: [
    {
      id: "profile-project-1",
      name: "InternPath 求职决策台",
      role: "全栈开发",
      description: "基于 React、FastAPI 和 SQLite 搭建个人求职分析工作台，支持 JD 分析、材料管理和历史沉淀。",
      techStack: ["React", "TypeScript", "Python", "FastAPI", "SQLite"],
      impact: "把岗位分析、简历改造和复盘流程集中到一个工作台。",
    },
  ],
  education: "计算机相关方向",
  preferredDirections: ["前端", "全栈", "AI 工具", "效率工具"],
  blockedDirections: ["销售", "纯运营"],
  targetCities: ["远程", "杭州", "上海"],
  remotePreference: "hybrid",
};

export function useProfile() {
  const [profile, setProfile] = useState<CandidateProfile>(() => loadFromStorage(PROFILE_KEY, defaultProfile));
  const [savedAt, setSavedAt] = useState<string>("");

  useEffect(() => {
    saveToStorage(PROFILE_KEY, profile);
  }, [profile]);

  function saveProfile(nextProfile: CandidateProfile) {
    setProfile(nextProfile);
    setSavedAt(new Date().toISOString());
  }

  return { profile, saveProfile, savedAt };
}
