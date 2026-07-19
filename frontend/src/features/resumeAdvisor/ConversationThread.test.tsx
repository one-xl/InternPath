import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationThread } from "./ConversationThread";

describe("ConversationThread", () => {
  afterEach(() => cleanup());

  it("explains the failed quality rules and the affected resume location", () => {
    render(
      <ConversationThread
        messages={[
          {
            id: "quality-1",
            sequence: 1,
            role: "assistant",
            content: "这条建议未通过本地质量检查，暂不提供复制。请告诉我希望怎样调整。",
            messageKind: "text",
            payload: {
              quality: {
                is_passed: false,
                score: 60,
                issues: ["建议与原文完全相同，未形成可执行修改", "复制文本不能包含 Markdown 标题"],
              },
              target: { locationLabel: "项目经历 · 第 1 条" },
              issue: "让项目成果更容易扫描",
            },
          },
        ]}
        suggestions={[]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("heading", { name: "这条建议暂不能复制" })).toBeInTheDocument();
    expect(screen.getByText("项目经历 · 第 1 条")).toBeInTheDocument();
    expect(screen.getByText("让项目成果更容易扫描")).toBeInTheDocument();
    expect(screen.getByText("建议与原文完全相同，未形成可执行修改")).toBeInTheDocument();
    expect(screen.getByText("复制文本不能包含 Markdown 标题")).toBeInTheDocument();
    expect(screen.getByText("本地质量分：60 / 100")).toBeInTheDocument();
  });

  it("renders only real streamed reply text inside the conversation", () => {
    const props = {
      messages: [],
      suggestions: [],
      onSuggestionAction: vi.fn().mockResolvedValue(undefined),
      onFocusSuggestion: vi.fn(),
      onQuestionAnswer: vi.fn().mockResolvedValue(undefined),
    };
    const { rerender } = render(<ConversationThread {...props} streamingContent="真实 token" />);

    expect(screen.getByLabelText("模型正在流式回复")).toHaveTextContent("真实 token");
    expect(screen.getByLabelText("简历顾问对话").querySelector("[role='status']")).not.toBeInTheDocument();

    rerender(<ConversationThread {...props} streamingContent="" />);

    expect(screen.queryByLabelText("模型正在流式回复")).not.toBeInTheDocument();
  });

  it("keeps only the last question without a later user reply active", () => {
    render(
      <ConversationThread
        messages={[
          { id: "question-1", sequence: 1, role: "assistant", content: "第一个问题", messageKind: "question", payload: {} },
          { id: "reply-1", sequence: 2, role: "user", content: "第一个回答", messageKind: "fact", payload: {} },
          { id: "question-2", sequence: 3, role: "assistant", content: "第二个问题", messageKind: "question", payload: {} },
        ]}
        suggestions={[]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("第一个问题")).toBeInTheDocument();
    expect(screen.getByText("第二个问题")).toBeInTheDocument();
    expect(screen.getByText("已回答 / 已失效")).toBeInTheDocument();
    expect(screen.getAllByRole("textbox", { name: "补充真实证据" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "提交事实" })).toHaveLength(1);
  });

  it("shows confirmed and declined facts retained for the active session", () => {
    render(
      <ConversationThread
        messages={[]}
        suggestions={[]}
        facts={[
          { id: "fact-1", claimKey: "requirement:redis", claimValue: "使用过 Redis 缓存热点查询", sourceType: "user_message", sourceId: "turn-1", status: "confirmed", scope: "session" },
          { id: "fact-2", claimKey: "requirement:kafka", claimValue: "没有 Kafka 相关真实经历", sourceType: "user_message", sourceId: "turn-2", status: "denied", scope: "global" },
        ]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("已记录事实")).toBeInTheDocument();
    expect(screen.getByText(/已确认 · 使用过 Redis 缓存热点查询 · 本次会话/)).toBeInTheDocument();
    expect(screen.getByText(/明确不存在 · 没有 Kafka 相关真实经历 · 长期/)).toBeInTheDocument();
  });
});
