export interface ProjectExperience {
  id: string;
  name: string;
  role: string;
  description: string;
  techStack: string[];
  impact: string;
}

export interface CandidateProfile {
  targetRole: string;
  resumeText: string;
  skillStack: string[];
  projects: ProjectExperience[];
  education: string;
  preferredDirections: string[];
  blockedDirections: string[];
  targetCities: string[];
  remotePreference: "remote" | "onsite" | "hybrid" | "any";
  name?: string;
  phone?: string;
  email?: string;
  gender?: string;
  birthDate?: string;
  politicalStatus?: string;
  hometown?: string;
  expectedSalary?: string;
  wechat?: string;
  gpa?: string;
}
