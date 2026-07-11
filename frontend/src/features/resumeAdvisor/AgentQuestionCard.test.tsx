import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentQuestionCard } from "./AgentQuestionCard";

describe("AgentQuestionCard", () => {
  afterEach(() => cleanup());

  it("records an explicit no-experience answer instead of hiding the question", () => {
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentQuestionCard
        message={{
          id: "question-1",
          sequence: 1,
          role: "assistant",
          content: "你是否有 Redis 相关结果？",
          messageKind: "question",
          payload: { questionKey: "requirement:redis", why: "没有证据不能写入简历", target: "项目经历" },
        }}
        onAnswer={onAnswer}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "没有这项经历" }));
    expect(onAnswer).toHaveBeenCalledWith("没有 redis 相关真实经历。", false);
    expect(screen.getByText("没有证据不能写入简历")).toBeInTheDocument();
  });

  it("saves an answer only when the user explicitly chooses to remember it", () => {
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentQuestionCard
        message={{
          id: "question-2", sequence: 2, role: "assistant", content: "是否有 Redis 经验证据？",
          messageKind: "question", payload: { questionKey: "requirement:redis" },
        }}
        onAnswer={onAnswer}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "将本次回答保存为长期事实" }));
    fireEvent.click(screen.getByRole("button", { name: "跳过" }));

    expect(onAnswer).toHaveBeenCalledWith("跳过 redis，暂不补充。", true);
  });
});
