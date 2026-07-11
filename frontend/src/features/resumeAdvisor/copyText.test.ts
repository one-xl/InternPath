import { describe, expect, it, vi } from "vitest";

import { copyText } from "./copyText";

describe("copyText", () => {
  it("falls back to document.execCommand when Clipboard API is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    const execCommand = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });

    await copyText("可复制的建议文本");

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });
});
