import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DisclosureTask, Revision } from "../../lib/types";
import { AnalysisProgress } from "./AnalysisProgress";
import { NewTaskDialog } from "./NewTaskDialog";

const revision: Revision = {
  id: "revision-test",
  task_id: "task-test",
  revision_number: 1,
  status: "exportable",
  context: {
    recipient: "internal_procurement_lead",
    organization: "northstar.example",
    recipient_id: "procurement.lead@northstar.example",
    purpose: "procurement_decision",
    channel: "collaboration_platform",
    classification: "confidential",
    policy_version: "1.0.0",
    sha256: "a".repeat(64),
  },
  source_sha256: "b".repeat(64),
  policy_sha256: "c".repeat(64),
  output_sha256: "d".repeat(64),
  decision_manifest_sha256: "e".repeat(64),
  created_at: "2026-08-02T12:00:00Z",
  action_counts: { keep: 4, remove: 2 },
  decisions: [],
};

describe("structured task flow", () => {
  it("keeps every policy input visible and purpose controlled", async () => {
    render(
      <NewTaskDialog
        open
        onCreate={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Recipient profile")).toBeInTheDocument();
    expect(screen.getByLabelText("Recipient organization")).toBeInTheDocument();
    expect(screen.getByLabelText("Recipient identity")).toBeInTheDocument();
    expect(screen.getByLabelText("Controlled purpose").tagName).toBe("SELECT");
    expect(screen.getByLabelText("Disclosure channel")).toBeInTheDocument();
    expect(screen.getByLabelText("Classification")).toBeInTheDocument();
    expect(screen.getByLabelText("Policy version")).toBeDisabled();
    expect(screen.queryByPlaceholderText(/purpose/i)).not.toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByLabelText("Scenario template"),
      "docx-response",
    );
    const classification = screen.getByLabelText("Classification") as HTMLSelectElement;
    expect(Array.from(classification.options).map((option) => option.value)).toEqual([
      "strictly_confidential",
    ]);
  });

  it("uploads a matching file only after purpose confirmation", async () => {
    const createdTask = { id: "task-test" } as DisclosureTask;
    const onCreate = vi.fn().mockResolvedValue(createdTask);
    render(
      <NewTaskDialog open onCreate={onCreate} onOpenChange={vi.fn()} />,
    );
    const file = new File(["synthetic"], "supplier-matrix.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    await userEvent.upload(screen.getByLabelText("Source document"), file);
    await userEvent.click(screen.getByRole("button", { name: "Create and analyze" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Confirm the controlled purpose");

    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create and analyze" }));

    expect(onCreate).toHaveBeenCalledWith(
      file,
      expect.objectContaining({
        recipient: "internal_procurement_lead",
        purpose: "procurement_decision",
      }),
      "demo-requester-procurement",
    );
  });

  it("renders named progress stages and a final result summary", () => {
    render(
      <AnalysisProgress
        events={[
          {
            revision_id: revision.id,
            sequence: 1,
            stage: "preflight",
            status: "pass",
            occurred_at: revision.created_at,
          },
          {
            revision_id: revision.id,
            sequence: 2,
            stage: "parse",
            status: "completed",
            occurred_at: revision.created_at,
          },
          {
            revision_id: revision.id,
            sequence: 3,
            stage: "semantic_classification",
            status: "completed",
            occurred_at: revision.created_at,
          },
        ]}
        revision={revision}
        running={false}
      />,
    );

    expect(screen.getByText("Deterministic scan")).toBeInTheDocument();
    expect(screen.getByText("Semantic classification")).toBeInTheDocument();
    expect(screen.getByText("Residual safety check")).toBeInTheDocument();
    expect(screen.getByText("6 policy decisions recorded")).toBeInTheDocument();
    fireEvent.click(document.body);
  });
});
