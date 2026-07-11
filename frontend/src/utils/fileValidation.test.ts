import { describe, expect, it } from "vitest";
import { validateResumeFile } from "./fileValidation";

describe("validateResumeFile", () => {
  it("accepts plain-text resumes", () => {
    const file = new File(["Project experience"], "resume.txt", { type: "text/plain" });

    expect(validateResumeFile(file)).toBeNull();
  });
});
