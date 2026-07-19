import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentQuestionCard } from "./AgentQuestionCard";

describe("AgentQuestionCard", () => {
  afterEach(() => cleanup());

  it("records an explicit no-experience answer instead of hiding the question", async () => {
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
        active
      />,
    );

    expect(screen.getByText("没有证据不能写入简历")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "没有这项经历" }));
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith("没有 redis 相关真实经历。", false));
    expect(screen.getByRole("status")).toHaveTextContent("已提交，正在继续分析。");
  });

  it("submits typed evidence and saves it only when the user chooses to remember it", async () => {
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentQuestionCard
        message={{
          id: "question-2", sequence: 2, role: "assistant", content: "是否有 Redis 经验证据？",
          messageKind: "question", payload: { questionKey: "requirement:redis" },
        }}
        onAnswer={onAnswer}
        active
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "将本次回答保存为长期事实" }));
    fireEvent.change(screen.getByRole("textbox", { name: "补充真实证据" }), { target: { value: "我用 Redis 缓存过热点查询，命中率约 80%。" } });
    fireEvent.click(screen.getByRole("button", { name: "提交事实" }));

    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith("我用 Redis 缓存过热点查询，命中率约 80%。", true));
  });

  it("locks controls while submitting and exposes a retryable error", async () => {
    let resolveAnswer: (() => void) | undefined;
    const onAnswer = vi.fn().mockImplementation(() => new Promise<void>((resolve) => { resolveAnswer = resolve; }));
    const firstQuestion = render(
      <AgentQuestionCard
        active
        message={{ id: "question-3", sequence: 3, role: "assistant", content: "请提供项目结果。", messageKind: "question", payload: {} }}
        onAnswer={onAnswer}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "补充真实证据" }), { target: { value: "上线后日活提升 10%。" } });
    fireEvent.click(screen.getByRole("button", { name: "提交事实" }));

    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "补充真实证据" })).toBeDisabled();
    resolveAnswer?.();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已提交，正在继续分析。"));
    firstQuestion.unmount();

    const rejectedAnswer = vi.fn().mockRejectedValue(new Error("网络错误"));
    render(
      <AgentQuestionCard
        active
        message={{ id: "question-4", sequence: 4, role: "assistant", content: "请提供职责。", messageKind: "question", payload: {} }}
        onAnswer={rejectedAnswer}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "补充真实证据" }), { target: { value: "我负责接口开发。" } });
    fireEvent.click(screen.getByRole("button", { name: "提交事实" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("网络错误"));
    expect(screen.getByRole("button", { name: "提交事实" })).toBeEnabled();
  });

  it("does not render answer controls for an inactive historical question", () => {
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentQuestionCard
        active={false}
        message={{ id: "question-5", sequence: 5, role: "assistant", content: "旧问题", messageKind: "question", payload: {} }}
        onAnswer={onAnswer}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("已回答 / 已失效");
    expect(screen.queryByRole("textbox", { name: "补充真实证据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交事实" })).not.toBeInTheDocument();
  });
});
