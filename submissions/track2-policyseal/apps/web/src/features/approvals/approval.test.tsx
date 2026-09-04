import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Approval, DisclosureTask, Revision } from "../../lib/types";
import { ExportPanel } from "../exports/ExportPanel";
import { ApprovalPanel } from "./ApprovalPanel";
import { DemoRoleSwitch } from "./DemoRoleSwitch";

const context = {
  recipient: "candidate_supplier" as const,
  organization: "candidate.example",
  recipient_id: "candidate@candidate.example",
  purpose: "contract_terms_preview" as const,
  channel: "corporate_email" as const,
  classification: "confidential" as const,
  policy_version: "1.0.0",
  sha256: "a".repeat(64),
};

function makeRevision(status: Revision["status"]): Revision {
  return {
    id: `revision-${status}`,
    task_id: "task-approval",
    revision_number: 1,
    status,
    context,
    source_sha256: "b".repeat(64),
    policy_sha256: "c".repeat(64),
    output_sha256: "d".repeat(64),
    decision_manifest_sha256: "e".repeat(64),
    created_at: "2026-08-02T12:00:00Z",
    action_counts: {},
    decisions: [],
  };
}

const task: DisclosureTask = {
  id: "task-approval",
  requester_id: "requester-approval",
  file_kind: "pdf",
  source_sha256: "b".repeat(64),
  created_at: "2026-08-02T12:00:00Z",
  revisions: [],
};

const pending: Approval = {
  id: "approval-pending",
  revision_id: "revision-awaiting_approval",
  status: "pending",
  binding_sha256: "f".repeat(64),
  requester_id: task.requester_id,
  reviewer_id: null,
  expires_at: "2026-08-03T12:00:00Z",
  consumed: false,
  reason_code: null,
};

describe("approval and export controls", () => {
  it("separates requester submission from reviewer resolution", async () => {
    const onRequest = vi.fn().mockResolvedValue(undefined);
    const onResolve = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <ApprovalPanel
        revision={makeRevision("awaiting_approval")}
        role="requester"
        task={task}
        onRequest={onRequest}
        onResolve={onResolve}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Request approval" }));
    expect(onRequest).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /Approve exact/ })).not.toBeInTheDocument();

    rerender(
      <ApprovalPanel
        approval={pending}
        revision={makeRevision("awaiting_approval")}
        role="policy_reviewer"
        task={task}
        onRequest={onRequest}
        onResolve={onResolve}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve exact revision" }));
    expect(onResolve).toHaveBeenCalledWith("approve");
    expect(screen.queryByRole("button", { name: "Request approval" })).not.toBeInTheDocument();
  });

  it("keeps every export locked for a blocked revision", () => {
    render(
      <ExportPanel
        revision={makeRevision("blocked")}
        onBusinessExported={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getByRole("button", { name: "Business output" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Evidence package" })).toBeDisabled();
    expect(screen.getByText("Downloads remain locked in this state.")).toBeInTheDocument();
  });

  it("labels the role switch as synthetic and changes role explicitly", async () => {
    const onRoleChange = vi.fn();
    render(<DemoRoleSwitch role="requester" onRoleChange={onRoleChange} />);
    expect(screen.getByText("Synthetic")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reviewer" }));
    expect(onRoleChange).toHaveBeenCalledWith("policy_reviewer");
  });
});
