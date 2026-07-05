export type WorkMode = "remote" | "onsite" | "hybrid" | "unknown";
export type JobLevel = "intern" | "campus" | "junior" | "middle" | "unknown";

export interface JobMeta {
  company: string;
  title: string;
  link: string;
  location: string;
  workMode: WorkMode;
  level: JobLevel;
}

export interface JobDraft extends JobMeta {
  jdText: string;
  targetType: string;
  jobDirection: string;
  candidateMaterial?: string;
  enableAgentResume?: boolean;
  // Legacy manual-material fields remain only for old local history compatibility.
  resumeText: string;
  projectText: string;
  skillsText: string;
  goalText: string;
  useDefaultProfile: boolean;
}
