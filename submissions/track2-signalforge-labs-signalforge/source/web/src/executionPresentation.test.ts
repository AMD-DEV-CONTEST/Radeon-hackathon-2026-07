import { describe, expect, it } from "vitest";
import type { ExecutionPlan } from "./types";
import {
  buildExecutionPresentation,
  executionPresentationSchema,
  routeLabel,
  sha256Hex,
  statusLabel
} from "./executionPresentation";

describe("buildExecutionPresentation", () => {
  it("projects one signed execution truth into summary, detail, and typed proof", () => {
    const presentation = buildExecutionPresentation(samplePlan());
    const context = presentation.phases.find((phase) => phase.id === "context");
    const specialist = context?.steps[0];

    expect(presentation.schemaVersion).toBe(executionPresentationSchema);
    expect(presentation.presentationSHA256).toMatch(/^[a-f0-9]{64}$/);
    expect(presentation.headline).toBe("Accounting specialist");
    expect(presentation.percentage).toBe(50);
    expect(context?.label).toBe("Evidence and specialists");
    expect(context?.requirementLabel).toBe("Required");
    expect(context?.waves).toEqual([
      expect.objectContaining({
        id: "wave-1",
        label: "Parallel wave 1",
        parallel: false
      })
    ]);
    expect(specialist).toEqual(expect.objectContaining({
      authorityLabel: "Accounting Reporting",
      routeLabel: "Local Radeon inference",
      requirementLabel: "Required"
    }));
    expect(specialist?.checklist[0]).toEqual(expect.objectContaining({
      authorityLabel: "Evidence authority",
      requirementLabel: "Required",
      references: [{
        id: "evidence-1",
        kind: "evidence",
        authority: "retrieval"
      }]
    }));
    expect(specialist?.checklist[1].references[0]).toEqual({
      id: "receipt-1",
      kind: "calculation",
      authority: "engine"
    });
  });

  it("keeps capability authorization distinct from an executed calculation receipt", () => {
    const plan = samplePlan();
    plan.steps[1].checklist.push({
      check_id: "capability-01",
      label: "Financial free cash flow authorized",
      status: "passed",
      authority: "capability",
      required: false,
      reference_ids: ["financial.free_cash_flow"],
      safe_detail: "The capability is allowlisted for this role."
    });

    const presentation = buildExecutionPresentation(plan);
    const specialist = presentation.phases.find((phase) => phase.id === "context")?.steps[0];
    expect(specialist?.checklist[2]).toEqual(expect.objectContaining({
      authorityLabel: "Capability authorization",
      references: [{
        id: "financial.free_cash_flow",
        kind: "authorization",
        authority: "capability"
      }]
    }));
  });

  it("does not present started or failed engine attempts as calculation receipts", () => {
    const plan = samplePlan();
    const checklist = plan.steps[1].checklist[1];
    checklist.status = "failed";
    checklist.reference_ids = ["engine-attempt-1", "receipt-unreleased"];

    const presentation = buildExecutionPresentation(plan);
    const specialist = presentation.phases.find((phase) => phase.id === "context")?.steps[0];
    expect(specialist?.checklist[1].references).toEqual([
      { id: "engine-attempt-1", kind: "lineage", authority: "engine" },
      { id: "receipt-unreleased", kind: "lineage", authority: "engine" }
    ]);
  });

  it("uses closed labels for terminal and route states without inventing explanations", () => {
    const plan = samplePlan();
    plan.status = "degraded";
    plan.steps[1].status = "degraded";
    plan.steps[1].degradation_code = "primary_route_unavailable";
    plan.steps[1].route = "radeon_api_to_local_rocm";

    const presentation = buildExecutionPresentation(plan);
    expect(presentation.statusLabel).toBe("Bounded subset");
    expect(presentation.attention).toBe(true);
    expect(presentation.phases[2].steps[0].routeLabel).toBe("Radeon primary, local fallback");
    expect(presentation.phases[2].steps[0].degradationCode).toBe("primary_route_unavailable");
  });

  it("keeps protected bodies outside the presentation contract", () => {
    const serialized = JSON.stringify(buildExecutionPresentation(samplePlan()));
    expect(serialized).not.toMatch(/chain.of.thought|raw.prompt|response.body|api.key|password/i);
  });

  it.each([
    ["pending", "Waiting"],
    ["ready", "Ready"],
    ["running", "In progress"],
    ["passed", "Verified"],
    ["failed", "Stopped safely"],
    ["degraded", "Bounded subset"],
    ["repairing", "Repairing"],
    ["skipped", "Not required"],
    ["cancelled", "Cancelled"],
    ["withheld", "Withheld"],
    ["unavailable", "Unavailable"]
  ] as const)("uses the closed presentation label for %s", (status, expected) => {
    expect(statusLabel(status)).toBe(expected);
  });

  it("keeps local and Radeon API execution routes visibly distinct", () => {
    expect(routeLabel("local_rocm")).toBe("Local Radeon inference");
    expect(routeLabel("radeon_api")).toBe("Radeon Cloud specialist");
    expect(routeLabel("radeon_api_to_local_rocm")).toBe("Radeon primary, local fallback");
  });

  it("hashes the exact expanded presentation deterministically", () => {
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    const first = buildExecutionPresentation(samplePlan());
    const second = buildExecutionPresentation(samplePlan());
    expect(first.presentationSHA256).toBe(second.presentationSHA256);

    const changed = samplePlan();
    changed.steps[1].safe_summary = "A different governed state.";
    expect(buildExecutionPresentation(changed).presentationSHA256).not.toBe(first.presentationSHA256);
  });
});

function samplePlan(): ExecutionPlan {
  const phase = (
    phase_id: string,
    order: number,
    mandatory: boolean,
    status: ExecutionPlan["status"],
    step_ids: string[]
  ): ExecutionPlan["phases"][number] => ({
    phase_id,
    order,
    safe_label: phase_id,
    safe_objective: `Run ${phase_id}.`,
    mandatory,
    status,
    step_ids,
    safe_summary: `${phase_id} status.`
  });

  return {
    schema_version: "signalforge/execution-plan/v1",
    run_id: "run-presentation",
    request_id: "request-presentation",
    plan_id: "plan-presentation",
    status: "running",
    created_at: "2026-07-26T12:00:00Z",
    started_at: "2026-07-26T12:00:01Z",
    total_steps: 2,
    terminal_steps: 1,
    progress_ratio: 0.5,
    max_parallel_specialists: 4,
    current_wave: 1,
    route_summary: ["local_rocm"],
    phases: [
      phase("interpretation", 1, true, "passed", ["interpret-request"]),
      phase("planning", 2, true, "passed", []),
      phase("context", 3, true, "running", ["context-accounting"]),
      phase("tools", 4, false, "pending", []),
      phase("review", 5, true, "pending", []),
      phase("synthesis", 6, true, "pending", []),
      phase("memory", 7, false, "pending", []),
      phase("release", 8, true, "pending", [])
    ],
    steps: [
      {
        step_id: "interpret-request",
        parent_phase_id: "interpretation",
        phase: "interpretation",
        kind: "control",
        safe_label: "Interpret request",
        safe_objective: "Resolve the request.",
        role_id: "request-interpreter/v1",
        mandatory: true,
        status: "passed",
        checklist: [],
        attempt: 1,
        max_attempts: 1,
        safe_summary: "The request passed."
      },
      {
        step_id: "context-accounting",
        parent_phase_id: "context",
        phase: "context",
        kind: "context",
        safe_label: "Accounting specialist",
        safe_objective: "Compile accounting context.",
        role_id: "accounting-reporting/v1",
        wave: 1,
        mandatory: true,
        status: "running",
        route: "local_rocm",
        checklist: [
          {
            check_id: "evidence-authority",
            label: "Authorize evidence",
            status: "running",
            authority: "retrieval",
            required: true,
            reference_ids: ["evidence-1"],
            safe_detail: "One authorized source is being checked."
          },
          {
            check_id: "tool-receipt",
            label: "Validate calculation",
            status: "passed",
            authority: "engine",
            required: false,
            reference_ids: ["receipt-1"],
            safe_detail: "The deterministic receipt passed."
          }
        ],
        attempt: 1,
        max_attempts: 2,
        safe_summary: "The specialist is compiling governed context."
      }
    ],
    last_sequence: 3,
    projection_sha256: "a".repeat(64)
  };
}
