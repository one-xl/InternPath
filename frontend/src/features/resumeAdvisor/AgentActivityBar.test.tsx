import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentActivityBar } from "./AgentActivityBar";

describe("AgentActivityBar", () => {
  afterEach(() => cleanup());

  it("shows public model, tool and cache telemetry outside the conversation", () => {
    render(
      <AgentActivityBar activity={{
        active: true,
        title: "GPT 正在流式生成回复",
        detail: "resume_copywriter",
        cacheLabel: "resume_advisor_draft_v1 命中",
        providerCacheLabel: "Provider 缓存命中 128 tokens",
        firstTokenMs: 842,
      }} />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("GPT 正在流式生成回复");
    expect(status).toHaveTextContent("resume_advisor_draft_v1 命中");
    expect(status).toHaveTextContent("首 token 842 ms");
  });
});
