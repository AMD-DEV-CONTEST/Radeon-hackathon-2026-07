import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  Decision,
  DisclosureContext,
  DisclosureTask,
  EvidenceRecord,
  ReviewData,
  ReviewRegion,
  Revision,
  Simulation,
} from "../../lib/types";
import { ContextMatrix, type MatrixColumn } from "./ContextMatrix";
import { DecisionInspector } from "./DecisionInspector";
import { ReviewWorkspace } from "./ReviewWorkspace";

const context = {
  recipient: "internal_procurement_lead" as const,
  organization: "northstar.example",
  recipient_id: "procurement.lead@northstar.example",
  purpose: "procurement_decision" as const,
  channel: "collaboration_platform" as const,
  classification: "confidential" as const,
  policy_version: "1.0.0",
  sha256: "a".repeat(64),
};

function decision(regionId: string, action: Decision["action"]): Decision {
  return {
    region_id: regionId,
    location: `xlsx:Supplier Comparison:${regionId}`,
    category: regionId === "B6" ? "supplier_identity" : "bank_payment",
    action,
    rule_ids: [`PS-${action.toUpperCase()}`],
    evidence_ids: ["EV-XLSX-001"],
    reason_code: `${action}_fixture`,
    reason: `The controlled policy selected ${action}.`,
    policy_version: "1.0.0",
    transform: action === "mask" ? "mask_last_four" : null,
  };
}

const regions: ReviewRegion[] = [
  {
    region_id: "B6",
    location: "xlsx:Supplier Comparison:B6",
    order: 1,
    category: "supplier_identity",
    source_text: "Aster Works Ltd.",
    output_preview: "Aster Works Ltd.",
    action: "keep",
    rule_ids: ["PS-KEEP"],
    rule_reasons: ["Keep required supplier identity."],
    evidence_ids: ["EV-XLSX-001"],
    reason_code: "keep_fixture",
    transform: null,
  },
  {
    region_id: "F6",
    location: "xlsx:Supplier Comparison:F6",
    order: 2,
    category: "bank_payment",
    source_text: "9900012345678901",
    output_preview: null,
    action: "remove",
    rule_ids: ["PS-REMOVE"],
    rule_reasons: ["Payment execution is outside purpose."],
    evidence_ids: ["EV-XLSX-001"],
    reason_code: "remove_fixture",
    transform: null,
  },
];

const columns: MatrixColumn[] = [
  { id: "internal", label: "Internal", status: "exportable", decisions: [decision("B6", "keep"), decision("F6", "remove")], formal: true },
  { id: "audit", label: "Audit", status: "exportable", decisions: [decision("B6", "keep"), decision("F6", "mask")], formal: false },
  { id: "bidder", label: "Bidder A", status: "exportable", decisions: [decision("B6", "keep"), decision("F6", "remove")], formal: false },
  { id: "personal", label: "Personal email", status: "blocked", decisions: [decision("B6", "block"), decision("F6", "block")], formal: false },
];

const revision: Revision = {
  id: "revision-1",
  task_id: "task-1",
  revision_number: 1,
  status: "exportable",
  context,
  source_sha256: "b".repeat(64),
  policy_sha256: "c".repeat(64),
  output_sha256: "d".repeat(64),
  decision_manifest_sha256: "e".repeat(64),
  created_at: "2026-08-02T12:00:00Z",
  action_counts: { keep: 1, remove: 1 },
  decisions: columns[0].decisions ?? [],
};

const task: DisclosureTask = {
  id: "task-1",
  requester_id: "demo-requester-procurement",
  file_kind: "xlsx",
  source_sha256: revision.source_sha256,
  created_at: revision.created_at,
  revisions: [revision],
};

const evidence: EvidenceRecord[] = [
  {
    id: "EV-XLSX-001",
    title: "Internal procurement view",
    tags: ["xlsx"],
    excerpt: "Bank accounts are excluded because payment execution is not the stated purpose.",
  },
];

const review: ReviewData = {
  revision_id: revision.id,
  task_id: task.id,
  file_kind: "xlsx",
  regions,
  evidence,
  preview_urls: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("review workspace", () => {
  it("foregrounds four recipient actions and drills down by stable region ID", async () => {
    const onSelect = vi.fn();
    render(
      <ContextMatrix
        columns={columns}
        regions={regions}
        selectedColumnId="internal"
        onSelectColumn={vi.fn()}
        onSelectDecision={onSelect}
      />,
    );

    expect(screen.getByText("Disclosure action matrix")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Personal email/ })).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("gridcell", {
        name: "Audit, xlsx:Supplier Comparison:F6, Mask",
      }),
    );
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "audit" }),
      expect.objectContaining({ region_id: "F6", action: "mask" }),
      expect.objectContaining({ region_id: "F6" }),
    );
  });

  it("keeps source, target, rules, and policy evidence synchronized", () => {
    render(
      <DecisionInspector
        contextLabel="Internal"
        decision={decision("F6", "remove")}
        evidence={evidence}
        region={regions[1]}
      />,
    );

    expect(screen.getByText("9900012345678901")).toBeInTheDocument();
    expect(screen.getByText("Not disclosed")).toBeInTheDocument();
    expect(screen.getByText("PS-REMOVE")).toBeInTheDocument();
    expect(screen.getByText(/Bank accounts are excluded/)).toBeInTheDocument();
  });

  it("keeps a what-if non-downloadable until formal confirmation", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        calls.push(path);
        if (path.endsWith("/review")) {
          return { ok: true, json: async () => review };
        }
        if (path.endsWith("/simulations")) {
          const body = JSON.parse(String(init?.body)) as { context: DisclosureContext };
          const isAudit = body.context.recipient === "external_financial_auditor";
          const simulation: Simulation = {
            id: `simulation-${body.context.recipient}`,
            task_id: task.id,
            base_revision_id: revision.id,
            context: { ...body.context, sha256: "f".repeat(64) },
            status: body.context.channel === "personal_email" ? "blocked" : "exportable",
            action_counts: isAudit ? { keep: 1, mask: 1 } : { keep: 1, remove: 1 },
            decisions: isAudit ? columns[1].decisions ?? [] : columns[2].decisions ?? [],
            downloadable: false,
          };
          return { ok: true, json: async () => simulation };
        }
        if (path.endsWith("/formal-context")) {
          return {
            ok: true,
            json: async () => ({ ...revision, id: "revision-2", revision_number: 2 }),
          };
        }
        throw new Error(`Unexpected request ${path}`);
      }),
    );
    const onFormalRevision = vi.fn().mockResolvedValue(undefined);
    render(
      <ReviewWorkspace
        apiState="ready"
        revision={revision}
        role="requester"
        task={task}
        onFormalRevision={onFormalRevision}
        onRevisionChanged={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const auditHeader = await screen.findByRole("columnheader", { name: /Audit/ });
    await waitFor(() => expect(auditHeader).toHaveTextContent("Exportable"));
    await userEvent.click(auditHeader);
    expect(await screen.findByText("Simulation only")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set as formal context" }));
    await userEvent.click(screen.getByRole("button", { name: "Create formal revision" }));

    await waitFor(() => expect(onFormalRevision).toHaveBeenCalled());
    expect(calls.some((path) => path.endsWith("/formal-context"))).toBe(true);
  });
});
