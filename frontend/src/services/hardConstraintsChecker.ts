import type { ChatModelConfig } from "../types/modelConfig";
import type { ParsedJobDescription } from "./jobParser";
import type { ParsedResume } from "../types/resume";
import { callGeminiWithConfig } from "./geminiClient";
import { safeParseModelJson } from "../utils/safeParseModelJson";

export interface HardRisk {
  constraint: string;
  type: "education" | "years" | "location" | "visa" | "graduation_date" | "availability" | "required_skill" | "other";
  status: "pass" | "fail" | "unknown";
  severity: "blocking" | "serious" | "minor";
  reason: string;
  evidence: string[];
}

export interface HardConstraintsResult {
  hard_risks: HardRisk[];
  has_blocking_risk: boolean;
}

const HardConstraintsSchema = {
  type: "object",
  properties: {
    hard_risks: {
      type: "array",
      items: {
        type: "object",
        properties: {
          constraint: { type: "string" },
          type: { type: "string", enum: ["education", "years", "location", "visa", "graduation_date", "availability", "required_skill", "other"] },
          status: { type: "string", enum: ["pass", "fail", "unknown"] },
          severity: { type: "string", enum: ["blocking", "serious", "minor"] },
          reason: { type: "string" },
          evidence: { type: "array", items: { type: "string" } }
        },
        required: ["constraint", "type", "status", "severity", "reason", "evidence"]
      }
    },
    has_blocking_risk: { type: "boolean" }
  },
  required: ["hard_risks", "has_blocking_risk"]
};

export async function checkHardConstraints(
  parsedJD: ParsedJobDescription,
  parsedResume: ParsedResume,
  chatConfig: ChatModelConfig
): Promise<HardConstraintsResult> {
  // If there are no hard constraints identified in the parsed JD, return pass immediately
  if (!parsedJD.hard_constraints || parsedJD.hard_constraints.length === 0) {
    return {
      hard_risks: [],
      has_blocking_risk: false
    };
  }

  const prompt = `
You are an objective recruitment screening auditor. Your task is to audit the candidate's resume against the hard constraints specified in the Job Description.

Hard Constraints to check:
${JSON.stringify(parsedJD.hard_constraints, null, 2)}

Candidate Profile Summary:
${JSON.stringify(parsedResume.extractedProfile || {}, null, 2)}

Candidate Raw Resume Text:
${parsedResume.cleanedText}

Instructions:
- Carefully evaluate if the candidate satisfies each hard constraint.
- Status must be "pass" (clearly meets), "fail" (clearly does not meet), or "unknown" (information not present in resume).
- Do not guess! If there is no mention of visa, student graduation date, or specific location availability, mark status as "unknown" and request verification in the reason.
- A severity of "blocking" means the failure is a complete showstopper (e.g., student status for an internship when already graduated, or completely missing degree level requirements).
- Output valid JSON only matching the schema.
`;

  try {
    const rawResult = await callGeminiWithConfig({
      config: chatConfig,
      prompt,
      forceJson: true,
      responseSchema: HardConstraintsSchema,
      overrideGenerationConfig: {
        responseMimeType: "application/json",
        temperature: 0.1,
        thinkingConfig: {
          thinkingLevel: "minimal"
        }
      }
    });

    const parsed = safeParseModelJson<any>(rawResult);

    return {
      hard_risks: Array.isArray(parsed.hard_risks) ? parsed.hard_risks.map((risk: any) => ({
        constraint: risk.constraint || "",
        type: risk.type || "other",
        status: risk.status || "unknown",
        severity: risk.severity || "minor",
        reason: risk.reason || "",
        evidence: Array.isArray(risk.evidence) ? risk.evidence : []
      })) : [],
      has_blocking_risk: Boolean(parsed.has_blocking_risk)
    };
  } catch (error) {
    console.error("[hardConstraintsChecker] checkHardConstraints failed:", error);
    return {
      hard_risks: [],
      has_blocking_risk: false
    };
  }
}
