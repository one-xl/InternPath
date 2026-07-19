import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionSidebar } from "./SessionSidebar";

describe("SessionSidebar", () => {
  afterEach(() => cleanup());

  it("exposes independent delete controls for the selected resume and each session", () => {
    const onDeleteResume = vi.fn();
    const onDeleteSession = vi.fn();

    render(
      <SessionSidebar
        sessions={[{ id: "session-1", resumeId: "resume-1", jdText: "JD", title: "Python 实习", sessionStatus: "SATISFIED" }]}
        selectedSessionId={null}
        onSelect={vi.fn()}
        resumes={[{ id: "resume-1", name: "resume.docx", size: 1, type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }]}
        selectedResumeId="resume-1"
        onResumeChange={vi.fn()}
        jdText=""
        onJdTextChange={vi.fn()}
        onStart={vi.fn()}
        starting={false}
        onUpload={vi.fn()}
        uploading={false}
        onDeleteResume={onDeleteResume}
        deletingResumeId={null}
        onDeleteSession={onDeleteSession}
        deletingSessionId={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除所选简历：resume.docx" }));
    fireEvent.click(screen.getByRole("button", { name: "删除会话：Python 实习" }));

    expect(onDeleteResume).toHaveBeenCalledWith("resume-1");
    expect(onDeleteSession).toHaveBeenCalledWith("session-1");
  });
});
