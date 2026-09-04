import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Approval, CopilotReply, DisclosureTask, Revision } from "../../lib/types";
import { ReviewCopilot } from "./ReviewCopilot";

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

const revision: Revision = {
  id: "revision-copilot-1",
  task_id: "task-copilot-1",
  revision_number: 1,
  status: "awaiting_approval",
  context,
  source_sha256: "b".repeat(64),
  policy_sha256: "c".repeat(64),
  output_sha256: "d".repeat(64),
  decision_manifest_sha256: "e".repeat(64),
  created_at: "2026-08-02T12:00:00Z",
  action_counts: { require_approval: 1 },
  decisions: [],
};

const task: DisclosureTask = {
  id: revision.task_id,
  requester_id: "requester-copilot",
  file_kind: "pdf",
  source_sha256: revision.source_sha256,
  created_at: revision.created_at,
  revisions: [revision],
};

function reply(turn: number): CopilotReply {
  return {
    thread_id: "thread-copilot-1",
    task_id: task.id,
    revision_id: revision.id,
    turn_number: turn,
    intent: turn === 2 ? "simulate" : turn === 3 ? "draft_exception" : "explain",
    text: `Grounded response ${turn}. Rules: PS-CONTRACT-004. Evidence: EV-CONTRACT-002.`,
    citations: [
      {
        location: "pdf:page:2:block:7",
        category: "nonstandard_obligation",
        action: "require_approval",
        rule_ids: ["PS-CONTRACT-004"],
        evidence_ids: ["EV-CONTRACT-002"],
      },
    ],
    simulation_id: turn === 2 ? "simulation-1" : null,
    exception_draft_id: turn === 3 ? "exception-draft-1" : null,
    model_dependent: false,
  };
}

const approval: Approval = {
  id: "approval-1",
  revision_id: revision.id,
  status: "pending",
  binding_sha256: "f".repeat(64),
  requester_id: task.requester_id,
  reviewer_id: null,
  expires_at: "2026-08-03T12:00:00Z",
  consumed: false,
  reason_code: null,
};

describe("ReviewCopilot", () => {
  it("preserves one task-local thread across three grounded turns and confirms submission", async () => {
    let turn = 0;
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const path = String(input);
        calls.push(path);
        if (path.endsWith("/api/copilot/threads")) {
          return {
            ok: true,
            json: async () => ({
              thread_id: "thread-copilot-1",
              task_id: task.id,
              revision_id: revision.id,
              display_reference: "Revision 1",
              turn_count: 0,
            }),
          };
        }
        if (path.includes("/messages")) {
          turn += 1;
          return { ok: true, json: async () => reply(turn) };
        }
        if (path.endsWith("/exception-draft-1/submit")) {
          return {
            ok: true,
            json: async () => ({
              draft: {
                id: "exception-draft-1",
                task_id: task.id,
                revision_id: revision.id,
                location: "pdf:page:2:block:7",
                category: "nonstandard_obligation",
                rule_ids: ["PS-CONTRACT-004"],
                evidence_ids: ["EV-CONTRACT-002"],
                status: "submitted",
                submitted: true,
              },
              approval,
            }),
          };
        }
        throw new Error(`Unexpected request ${path}`);
      }),
    );
    const onSelectLocation = vi.fn();
    const onApprovalCreated = vi.fn();
    render(
      <ReviewCopilot
        apiState="ready"
        revision={revision}
        role="requester"
        selectedLocation="pdf:page:1:block:1"
        task={task}
        onApprovalCreated={onApprovalCreated}
        onSelectLocation={onSelectLocation}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Explain the selected decision." }));
    expect(await screen.findByText("Grounded response 1. Rules: PS-CONTRACT-004. Evidence: EV-CONTRACT-002.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /pdf:page:2:block:7/ }));
    expect(onSelectLocation).toHaveBeenCalledWith("pdf:page:2:block:7");

    await userEvent.click(
      screen.getByRole("button", { name: "What if the purpose is annual financial audit?" }),
    );
    expect(await screen.findByText("Grounded response 2. Rules: PS-CONTRACT-004. Evidence: EV-CONTRACT-002.")).toBeInTheDocument();
    expect(screen.getByText("Simulation / non-downloadable")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Draft an exception for the custom SLA." }));
    expect(await screen.findByText("Grounded response 3. Rules: PS-CONTRACT-004. Evidence: EV-CONTRACT-002.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Submit request" }));
    expect(screen.getByText("Submit exception request?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm submission" }));

    await waitFor(() => expect(onApprovalCreated).toHaveBeenCalledWith(approval));
    expect(calls.filter((path) => path.endsWith("/api/copilot/threads"))).toHaveLength(1);
    expect(calls.filter((path) => path.includes("/messages"))).toHaveLength(3);
    expect(screen.queryByText(/hidden reasoning/i)).not.toBeInTheDocument();
  });
});
