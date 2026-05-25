import type { ChatModelConfig } from "../types/modelConfig";
import { callGeminiWithConfig } from "./geminiClient";
import { safeParseModelJson } from "../utils/safeParseModelJson";

export interface ParsedJobRequirement {
  id: string;
  text: string;
  category: "skill" | "experience" | "education" | "responsibility" | "domain" | "tool" | "language" | "soft_skill" | "other";
  priority: "must_have" | "nice_to_have" | "unknown";
  is_hard_requirement: boolean;
  keywords: string[];
  reason: string;
}

export interface HardConstraint {
  type: "education" | "years" | "location" | "visa" | "graduation_date" | "availability" | "work_auth" | "other";
  text: string;
  blocking_level: "blocking" | "serious" | "minor" | "unknown";
}

export interface ParsedJobDescription {
  job_title: string;
  company: string;
  location: string;
  employment_type: "internship" | "full_time" | "part_time" | "contract" | "unknown";
  work_mode: "remote" | "onsite" | "hybrid" | "unknown";
  requirements: ParsedJobRequirement[];
  responsibilities: string[];
  hard_constraints: HardConstraint[];
  nice_to_have: string[];
  raw_text: string;
}

const JobParserSchema = {
  type: "object",
  properties: {
    job_title: { type: "string" },
    company: { type: "string" },
    location: { type: "string" },
    employment_type: { type: "string", enum: ["internship", "full_time", "part_time", "contract", "unknown"] },
    work_mode: { type: "string", enum: ["remote", "onsite", "hybrid", "unknown"] },
    requirements: {
      type: "array",
      items: {
        type: "object",
        properties: {
          id: { type: "string" },
          text: { type: "string" },
          category: { type: "string", enum: ["skill", "experience", "education", "responsibility", "domain", "tool", "language", "soft_skill", "other"] },
          priority: { type: "string", enum: ["must_have", "nice_to_have", "unknown"] },
          is_hard_requirement: { type: "boolean" },
          keywords: { type: "array", items: { type: "string" } },
          reason: { type: "string" }
        },
        required: ["id", "text", "category", "priority", "is_hard_requirement", "keywords", "reason"]
      }
    },
    responsibilities: { type: "array", items: { type: "string" } },
    hard_constraints: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: { type: "string", enum: ["education", "years", "location", "visa", "graduation_date", "availability", "work_auth", "other"] },
          text: { type: "string" },
          blocking_level: { type: "string", enum: ["blocking", "serious", "minor", "unknown"] }
        },
        required: ["type", "text", "blocking_level"]
      }
    },
    nice_to_have: { type: "array", items: { type: "string" } }
  },
  required: ["job_title", "company", "location", "employment_type", "work_mode", "requirements", "responsibilities", "hard_constraints", "nice_to_have"]
};

export async function parseJobDescription(
  jdText: string,
  chatConfig: ChatModelConfig
): Promise<ParsedJobDescription> {
  const prompt = `
You are a rigorous JD analysis assistant. Your task is to split a Job Description into structural requirements and constraints.

Requirements:
- Split the JD into atomic, distinct requirements. Each requirement should have a unique id (e.g. req_001, req_002...).
- For each requirement, determine its priority: "must_have" vs "nice_to_have". Must-haves represent key requirements that are mandatory for passing the resume screen.
- Identify hard constraints such as degree level, years of experience, specific graduation date range, onsite/remote location, visa sponsorship, or key stack.
- Output valid JSON only conforming to the requested schema.

JD Text to parse:
${jdText}
`;

  try {
    const rawResult = await callGeminiWithConfig({
      config: chatConfig,
      prompt,
      forceJson: true,
      responseSchema: JobParserSchema,
      overrideGenerationConfig: {
        responseMimeType: "application/json",
        temperature: 0.1,
        thinkingConfig: {
          thinkingLevel: "minimal"
        }
      }
    });

    const parsed = safeParseModelJson<any>(rawResult);

    // Normalize requirements robustly
    let requirements = Array.isArray(parsed.requirements)
      ? parsed.requirements
          .map((req: any, index: number) => ({
            id: req.id || `req_${String(index + 1).padStart(3, "0")}`,
            text: (req.text || req.requirement || req.description || "").trim(),
            category: req.category || "other",
            priority: req.priority || "unknown",
            is_hard_requirement: Boolean(req.is_hard_requirement),
            keywords: Array.isArray(req.keywords) ? req.keywords : [],
            reason: req.reason || ""
          }))
          .filter((req: any) => req.text.length > 0)
      : [];

    if (requirements.length === 0) {
      console.warn("[jobParser] Requirements list is empty. Using default requirement fallback.");
      requirements = [
        {
          id: "req_001",
          text: jdText.substring(0, 300).trim() + "...",
          category: "other",
          priority: "must_have",
          is_hard_requirement: false,
          keywords: [],
          reason: "JD 结构化提取未识别到要求，降级为全文模糊匹配"
        }
      ];
    }

    return {
      job_title: parsed.job_title || "未知岗位",
      company: parsed.company || "未知公司",
      location: parsed.location || "未注明地点",
      employment_type: parsed.employment_type || "unknown",
      work_mode: parsed.work_mode || "unknown",
      requirements,
      responsibilities: Array.isArray(parsed.responsibilities) ? parsed.responsibilities : [],
      hard_constraints: Array.isArray(parsed.hard_constraints) ? parsed.hard_constraints.map((hc: any) => ({
        type: hc.type || "other",
        text: hc.text || "",
        blocking_level: hc.blocking_level || "unknown"
      })) : [],
      nice_to_have: Array.isArray(parsed.nice_to_have) ? parsed.nice_to_have : [],
      raw_text: jdText
    };
  } catch (error) {
    console.error("[jobParser] parseJobDescription failed, using fallback:", error);
    // Safe fallback so that the pipeline never crashes
    return getFallbackJobDescription(jdText);
  }
}

function getFallbackJobDescription(jdText: string): ParsedJobDescription {
  return {
    job_title: "岗位分析 (未解析)",
    company: "待投递公司",
    location: "未注明地点",
    employment_type: "unknown",
    work_mode: "unknown",
    requirements: [
      {
        id: "req_001",
        text: jdText.substring(0, 200) + "...",
        category: "other",
        priority: "must_have",
        is_hard_requirement: false,
        keywords: [],
        reason: "JD 解析失败，降级为全文粗糙分析"
      }
    ],
    responsibilities: [],
    hard_constraints: [],
    nice_to_have: [],
    raw_text: jdText
  };
}
