import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationThread } from "./ConversationThread";
import type { AdvisorMessage, ResumeSuggestion } from "./types";

function suggestion(id: string, issue: string): ResumeSuggestion {
  return {
    id,
    version: 1,
    target: {
      blockId: `block-${id}`,
      sectionId: "experience",
      sectionName: "Experience",
      sourceFormat: "txt",
      locationLabel: `Location for ${id}`,
      locatorConfidence: "exact",
    },
    priority: "medium",
    issue,
    originalText: `Original ${id}`,
    proposedText: `Proposed ${id}`,
    copyText: `Proposed ${id}`,
    rationale: `Reason for ${id}`,
    expectedImpact: "Clearer wording",
    jdRequirementIds: [],
    resumeEvidenceBlockIds: [],
    userFactIds: [],
    factStatus: "supported",
    factIssues: [],
    status: "proposed",
  };
}

describe("ConversationThread", () => {
  afterEach(() => cleanup());

  it("renders HRCritic feedback as an ordinary assistant reply instead of a large gate card", () => {
    const { container } = render(
      <ConversationThread
        messages={[
          {
            id: "quality-1",
            sequence: 1,
            role: "assistant",
            content: "改写没有清楚说明候选人的实际贡献。",
            messageKind: "error",
            payload: {
              errorCode: "quality_gate_failed",
              quality: {
                is_passed: false,
                score: 60,
                reviewer: "hr_critic",
                issues: ["建议与原文完全相同，未形成可执行修改"],
                hr_review: {
                  critique: "改写没有清楚说明候选人的实际贡献。",
                  suggestions: "保留原有职责边界，并补充已存在的交付证据。",
                  factual_fidelity: {
                    verdict: "fail",
                    rationale: "改写把协助表述成了独立负责。",
                    evidence_basis: ["原文只说明协助接口开发。"],
                  },
                },
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

    expect(screen.queryByLabelText("审查结果")).not.toBeInTheDocument();
    expect(screen.getByText("改写没有清楚说明候选人的实际贡献。")).toBeInTheDocument();
    expect(container.querySelector(".resume-advisor-message.assistant")).toHaveTextContent("改写没有清楚说明候选人的实际贡献。");
  });

  it("keeps empty harness events out of assistant bubbles and exposes structured errors", () => {
    const { container } = render(
      <ConversationThread
        messages={[
          {
            id: "model-error",
            sequence: 1,
            role: "assistant",
            content: "",
            messageKind: "error",
            payload: {
              mode: "suggestion_generation",
              modelStatus: "unavailable",
              errorCode: "resume_advisor_suggestion_generation_unavailable",
            },
          },
          {
            id: "scan",
            sequence: 2,
            role: "assistant",
            content: "",
            messageKind: "resume_scan",
            payload: { scanKey: "scan-1" },
          },
        ]}
        suggestions={[]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByLabelText("处理状态")).toHaveTextContent("suggestion_generation");
    expect(screen.getByLabelText("处理状态")).toHaveTextContent("unavailable");
    expect(screen.getByLabelText("处理状态")).toHaveTextContent("resume_advisor_suggestion_generation_unavailable");
    expect(container.querySelector(".resume-advisor-message.assistant")).toBeNull();
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

  it("renders legacy questions as ordinary chat without embedded answer controls", () => {
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
    expect(screen.queryByText("已回答 / 已失效")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "补充真实证据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交事实" })).not.toBeInTheDocument();
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

  it("orders persisted messages by sequence, preserves equal-sequence input order, and does not mutate props", () => {
    const messages: AdvisorMessage[] = [
      { id: "new-user", sequence: 4, role: "user", content: "New user message", messageKind: "text", payload: {} },
      { id: "same-sequence-first", sequence: 2, role: "assistant", content: "First equal sequence", messageKind: "text", payload: {} },
      { id: "first-persisted", sequence: 1, role: "assistant", content: "First persisted message", messageKind: "text", payload: {} },
      { id: "same-sequence-second", sequence: 2, role: "assistant", content: "Second equal sequence", messageKind: "text", payload: {} },
    ];
    const inputOrder = messages.map((message) => message.id);

    const { container } = render(
      <ConversationThread
        messages={messages}
        suggestions={[]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect([...container.querySelectorAll(".resume-advisor-message")].map((message) => message.textContent)).toEqual([
      "First persisted message",
      "First equal sequence",
      "Second equal sequence",
      "New user message",
    ]);
    expect(messages.map((message) => message.id)).toEqual(inputOrder);
  });

  it("keeps legacy messages with missing or non-finite sequence values stable after sequenced turns", () => {
    const messages = [
      { id: "legacy-missing", role: "assistant", content: "Legacy missing", messageKind: "text", payload: {} },
      { id: "later", sequence: 3, role: "assistant", content: "Later", messageKind: "text", payload: {} },
      { id: "legacy-nan", sequence: Number.NaN, role: "assistant", content: "Legacy NaN", messageKind: "text", payload: {} },
      { id: "first", sequence: 1, role: "assistant", content: "First", messageKind: "text", payload: {} },
    ] as AdvisorMessage[];

    const { container } = render(
      <ConversationThread
        messages={messages}
        suggestions={[]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect([...container.querySelectorAll(".resume-advisor-message")].map((message) => message.textContent)).toEqual([
      "First",
      "Later",
      "Legacy missing",
      "Legacy NaN",
    ]);
  });

  it("places a live persisted insert by its durable sequence", () => {
    const props = {
      suggestions: [],
      onSuggestionAction: vi.fn().mockResolvedValue(undefined),
      onFocusSuggestion: vi.fn(),
      onQuestionAnswer: vi.fn().mockResolvedValue(undefined),
    };
    const { container, rerender } = render(
      <ConversationThread
        {...props}
        messages={[
          { id: "first", sequence: 1, role: "assistant", content: "First", messageKind: "text", payload: {} },
          { id: "third", sequence: 3, role: "assistant", content: "Third", messageKind: "text", payload: {} },
        ]}
      />,
    );

    rerender(
      <ConversationThread
        {...props}
        messages={[
          { id: "third", sequence: 3, role: "assistant", content: "Third", messageKind: "text", payload: {} },
          { id: "second", sequence: 2, role: "user", content: "Second", messageKind: "text", payload: {} },
          { id: "first", sequence: 1, role: "assistant", content: "First", messageKind: "text", payload: {} },
        ]}
      />,
    );

    expect([...container.querySelectorAll(".resume-advisor-message")].map((message) => message.textContent)).toEqual([
      "First",
      "Second",
      "Third",
    ]);
  });

  it("keeps both linked and legacy-unbound suggestion cards out of the conversation", () => {
    render(
      <ConversationThread
        messages={[
          { id: "user-action", sequence: 4, role: "user", content: "New user action", messageKind: "text", payload: { suggestionId: "linked" } },
          { id: "later-note", sequence: 3, role: "assistant", content: "Later assistant note", messageKind: "text", payload: {} },
          { id: "follow-up", sequence: 2, role: "assistant", content: "Assistant follow-up", messageKind: "text", payload: { suggestionId: "unbound" } },
          { id: "linked-message", sequence: 1, role: "assistant", content: "Linked suggestion announcement", messageKind: "suggestion", payload: { suggestionId: "linked" } },
        ]}
        suggestions={[suggestion("unbound", "Unbound suggestion"), suggestion("linked", "Linked suggestion")]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("Linked suggestion announcement")).toBeInTheDocument();
    expect(screen.getByText("Assistant follow-up")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Linked suggestion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Unbound suggestion" })).not.toBeInTheDocument();
  });

  it("does not expose suggestion-card controls inside the dialogue", async () => {
    render(
      <ConversationThread
        messages={[
          { id: "linked-message", sequence: 1, role: "assistant", content: "", messageKind: "suggestion", payload: { suggestionId: "linked" } },
        ]}
        suggestions={[suggestion("linked", "Linked suggestion")]}
        onSuggestionAction={vi.fn().mockResolvedValue(undefined)}
        onFocusSuggestion={vi.fn()}
        onQuestionAnswer={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.queryByRole("textbox", { name: "修改要求" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "请求修改" })).not.toBeInTheDocument();
  });
});
