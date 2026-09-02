import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ExecutionPlan } from "../types";
import { LiveExecutionPlan } from "./LiveExecutionPlan";

const phases: ExecutionPlan["phases"] = [
  {
    phase_id: "interpretation", order: 1, safe_label: "Interpretation",
    safe_objective: "Resolve the governed request.", mandatory: true, status: "passed",
    step_ids: ["interpret-request"], safe_summary: "The request passed."
  },
  {
    phase_id: "planning", order: 2, safe_label: "Planning",
    safe_objective: "Freeze the bounded plan.", mandatory: true, status: "passed",
    step_ids: [], safe_summary: "The plan passed."
  },
  {
    phase_id: "context", order: 3, safe_label: "Context",
    safe_objective: "Compile governed specialist context.", mandatory: true, status: "running",
    step_ids: ["context-01"], safe_summary: "Context activity is running."
  },
  {
    phase_id: "tools", order: 4, safe_label: "Tools",
    safe_objective: "Release validated deterministic receipts.", mandatory: false, status: "passed",
    step_ids: [], safe_summary: "One tool activity passed."
  },
  {
    phase_id: "review", order: 5, safe_label: "Review",
    safe_objective: "Independently challenge the evidence.", mandatory: true, status: "pending",
    step_ids: [], safe_summary: "Review is waiting."
  },
  {
    phase_id: "synthesis", order: 6, safe_label: "Synthesis",
    safe_objective: "Compose one bounded answer.", mandatory: true, status: "pending",
    step_ids: ["synthesis-01"], safe_summary: "Synthesis is waiting."
  },
  {
    phase_id: "memory", order: 7, safe_label: "Memory",
    safe_objective: "Apply explicit local retention.", mandatory: false, status: "pending",
    step_ids: [], safe_summary: "Memory preference is waiting."
  },
  {
    phase_id: "release", order: 8, safe_label: "Release",
    safe_objective: "Release only after mandatory gates pass.", mandatory: true, status: "pending",
    step_ids: [], safe_summary: "Release is waiting."
  }
];

const plan: ExecutionPlan = {
  schema_version: "signalforge/execution-plan/v1",
  run_id: "run-test",
  request_id: "request-test",
  plan_id: "plan-test",
  status: "running",
  created_at: "2026-07-25T12:00:00Z",
  started_at: "2026-07-25T12:00:00Z",
  total_steps: 3,
  terminal_steps: 1,
  progress_ratio: 1 / 3,
  max_parallel_specialists: 4,
  current_wave: 1,
  phases,
  last_sequence: 3,
  projection_sha256: "a".repeat(64),
  steps: [
    {
      step_id: "interpret-request",
      parent_phase_id: "interpretation",
      phase: "interpretation",
      kind: "control",
      safe_label: "Interpret request",
      safe_objective: "Identify the governed research intent and scope.",
      role_id: "request-interpreter/v1",
      mandatory: true,
      status: "passed",
      checklist: [{
        check_id: "request-contract",
        label: "Validate request contract",
        status: "passed",
        authority: "contract",
        required: true,
        safe_detail: "Request envelope accepted."
      }],
      attempt: 1,
      max_attempts: 1,
      safe_summary: "The governed request contract passed."
    },
    {
      step_id: "context-01",
      parent_phase_id: "context",
      phase: "context",
      kind: "context",
      safe_label: "Accounting Reporting",
      safe_objective: "Check accounting evidence.",
      role_id: "accounting-reporting/v1",
      wave: 1,
      depends_on: ["interpret-request"],
      mandatory: true,
      status: "running",
      route_reason_code: "intent_requires_specialist",
      checklist: [
        {
          check_id: "evidence-authority",
          label: "Authorize evidence context",
          status: "running",
          authority: "retrieval",
          required: true,
          reference_ids: ["evidence-1"]
        },
        {
          check_id: "tool-receipt",
          label: "Free cash flow receipt validated",
          status: "passed",
          authority: "engine",
          required: false,
          reference_ids: ["receipt-1"]
        }
      ],
      attempt: 1,
      max_attempts: 2,
      reference_ids: ["packet-1"],
      safe_summary: "The specialist is compiling governed context."
    },
    {
      step_id: "synthesis-01",
      parent_phase_id: "synthesis",
      phase: "synthesis",
      kind: "synthesis",
      safe_label: "Final synthesis",
      safe_objective: "Release one evidence-grounded answer.",
      role_id: "final-research-analyst/v1",
      depends_on: ["context-01"],
      mandatory: true,
      status: "pending",
      checklist: [],
      attempt: 0,
      max_attempts: 2,
      safe_summary: "Waiting for its dependencies."
    }
  ]
};

describe("LiveExecutionPlan", () => {
  it("shows live progress and expands each governed stage", () => {
    const onProof = vi.fn();
    const onCalculations = vi.fn();
    const onLineage = vi.fn();
    render(
      <LiveExecutionPlan
        plan={plan}
        traceID="80c42f9bdbda413b9f86413db94ed20a"
        running
        onProof={onProof}
        onCalculations={onCalculations}
        onLineage={onLineage}
      />
    );

    expect(screen.getByRole("heading", { name: "Accounting Reporting" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "33% closed" })).toHaveAttribute("aria-valuetext", "1 of 3 planned steps closed");
    expect(screen.getByText((_, element) => element?.textContent === "1 / 3 closed")).toBeInTheDocument();
    expect(screen.getByText("Check accounting evidence.")).toBeVisible();
    const phaseRail = screen.getByRole("list", { name: "Execution phases" });
    expect(phaseRail.querySelectorAll("li")).toHaveLength(8);
    expect(Array.from(phaseRail.querySelectorAll("li"), (item) => item.textContent?.replace(/^\d+/, ""))).toEqual([
      "Interpretation", "Planning", "Evidence and specialists", "Deterministic tools",
      "Independent review", "Synthesis", "Optional memory", "Release gate"
    ]);
    expect(phaseRail.querySelector('[aria-current="step"]')).toHaveTextContent("Evidence and specialists");
    expect(screen.getByLabelText("Workspace run identity")).toHaveTextContent("run run-test");
    expect(screen.getByLabelText("Workspace run identity")).toHaveTextContent("trace 80c42f9bdbda");

    fireEvent.click(screen.getAllByRole("button", { name: "Open evidence" })[0]);
    expect(onProof).toHaveBeenCalledWith(["evidence-1"]);

    const tools = screen.getByLabelText("Tools phase");
    fireEvent.click(tools.querySelector("summary")!);
    expect(screen.getByText("Deterministic engine · Supporting")).toBeVisible();
    const calculation = screen.getByText("Free cash flow receipt validated").closest("details")!;
    fireEvent.click(calculation.querySelector("summary")!);
    fireEvent.click(screen.getByRole("button", { name: "Open calculation" }));
    expect(onCalculations).toHaveBeenCalledWith(["receipt-1"]);
    fireEvent.click(screen.getAllByRole("button", { name: "Inspect lineage" })[1]);
    expect(onLineage).toHaveBeenCalledOnce();
  });

  it("states the privacy boundary explicitly", () => {
    render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    expect(screen.getByText(/never private chain-of-thought/i)).toBeInTheDocument();
    expect(screen.queryByText(/raw prompt/i)).not.toBeInTheDocument();
  });

  it("does not present an authorized capability as an executed receipt", () => {
    const authorizationPlan: ExecutionPlan = {
      ...plan,
      phases: plan.phases.map((phase) => phase.phase_id === "tools"
        ? { ...phase, status: "pending", safe_summary: "No deterministic operation has executed." }
        : phase),
      steps: plan.steps.map((step) => step.step_id === "context-01" ? {
        ...step,
        checklist: [{
          check_id: "capability-01",
          label: "Financial free cash flow authorized",
          status: "passed",
          authority: "capability",
          required: false,
          reference_ids: ["financial.free_cash_flow"],
          safe_detail: "The capability is allowlisted for this role."
        }]
      } : step)
    };
    render(
      <LiveExecutionPlan
        plan={authorizationPlan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    expect(screen.getByText("Financial free cash flow authorized")).toBeVisible();
    expect(screen.getByText("Capability authorization · Supporting")).toBeVisible();
    expect(screen.queryByText(/receipt-backed checks/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open calculation" })).not.toBeInTheDocument();
  });

  it("expands receipt proof from a standalone deterministic tool stage without duplication", () => {
    const onCalculations = vi.fn();
    const toolPlan: ExecutionPlan = {
      ...plan,
      total_steps: 4,
      terminal_steps: 2,
      progress_ratio: 0.5,
      phases: plan.phases.map((phase) => phase.phase_id === "tools" ? {
        ...phase,
        step_ids: ["fixture-calculation"],
        safe_summary: "One deterministic calculation record passed contract checks."
      } : phase),
      steps: [...plan.steps.map((step) => step.step_id === "context-01"
        ? { ...step, checklist: step.checklist.filter((item) => item.authority !== "engine") }
        : step), {
        step_id: "fixture-calculation",
        parent_phase_id: "tools",
        phase: "tools",
        kind: "tool",
        safe_label: "Run deterministic calculations",
        safe_objective: "Execute governed formulas and expose only validated receipt metadata.",
        role_id: "deterministic-engine/v1",
        mandatory: false,
        status: "passed",
        route: "local_deterministic",
        route_reason_code: "deterministic_receipt",
        checklist: [{
          check_id: "tool-a1b2c3",
          label: "Free cash flow metadata accepted",
          status: "passed",
          authority: "engine",
          required: false,
          reference_ids: ["engine-fixture-receipt-2", "receipt-2"],
          safe_detail: "The financial engine completed free cash flow with one contract-valid output."
        }],
        attempt: 1,
        max_attempts: 1,
        safe_summary: "1 of 1 deterministic calculation records passed contract checks."
      }]
    };
    render(
      <LiveExecutionPlan
        plan={toolPlan}
        running
        onProof={vi.fn()}
        onCalculations={onCalculations}
        onLineage={vi.fn()}
      />
    );

    const tools = screen.getByLabelText("Tools phase");
    fireEvent.click(tools.querySelector("summary")!);
    const toolStep = screen.getByLabelText("Run deterministic calculations step");
    fireEvent.click(toolStep.querySelector("summary")!);
    expect(screen.getAllByText("Free cash flow metadata accepted")).toHaveLength(1);

    const receipt = screen.getByText("Free cash flow metadata accepted").closest("details")!;
    fireEvent.click(receipt.querySelector("summary")!);
    fireEvent.click(screen.getByRole("button", { name: "Open calculation" }));
    expect(onCalculations).toHaveBeenCalledWith(["receipt-2"]);
  });

  it("keeps the signed plan visible while the event stream reconnects", () => {
    render(
      <LiveExecutionPlan
        plan={plan}
        running
        connection="recovering"
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting to signed plan");
    expect(screen.getByRole("heading", { name: "Accounting Reporting" })).toBeInTheDocument();
  });

  it("lets phases and their steps expand independently", () => {
    render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    const phase = screen.getByLabelText("Interpretation phase");
    const step = screen.getByLabelText("Interpret request step");
    expect(phase).not.toHaveAttribute("open");

    fireEvent.click(phase.querySelector("summary")!);
    expect(phase).toHaveAttribute("open");
    expect(step).not.toHaveAttribute("open");

    fireEvent.click(step.querySelector("summary")!);
    expect(step).toHaveAttribute("open");
    expect(screen.getByText("Identify the governed research intent and scope.")).toBeVisible();
  });

  it("expands and collapses phases and steps from the keyboard", () => {
    render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    const phase = screen.getByLabelText("Interpretation phase");
    const phaseSummary = phase.querySelector("summary")!;
    const step = screen.getByLabelText("Interpret request step");
    const stepSummary = step.querySelector("summary")!;

    fireEvent.keyDown(phaseSummary, { key: "Enter" });
    expect(phase).toHaveAttribute("open");
    fireEvent.keyDown(stepSummary, { key: " " });
    expect(step).toHaveAttribute("open");

    fireEvent.keyDown(stepSummary, { key: "Enter" });
    fireEvent.keyDown(phaseSummary, { key: " " });
    expect(step).not.toHaveAttribute("open");
    expect(phase).not.toHaveAttribute("open");
  });

  it("collapses successful phases and keeps bounded outcomes visible after completion", () => {
    const complete: ExecutionPlan = {
      ...plan,
      status: "degraded",
      terminal_steps: 3,
      progress_ratio: 1,
      phases: plan.phases.map((phase) => ({
        ...phase,
        status: phase.phase_id === "context" ? "degraded" : "passed"
      })),
      steps: plan.steps.map((step) => ({
        ...step,
        status: step.step_id === "context-01" ? "degraded" : "passed"
      }))
    };
    render(
      <LiveExecutionPlan
        plan={complete}
        running={false}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    expect(screen.getByLabelText("Interpretation phase")).not.toHaveAttribute("open");
    expect(screen.getByLabelText("Context phase")).toHaveAttribute("open");
    expect(screen.getByLabelText("Accounting Reporting step")).toHaveAttribute("open");
  });

  it("renders routes, fallback, repair, failure, and withheld states as safe operational facts", () => {
    const exceptional: ExecutionPlan = {
      ...plan,
      status: "failed",
      total_steps: 5,
      terminal_steps: 4,
      progress_ratio: 0.8,
      phases: plan.phases.map((phase) => {
        const status = phase.phase_id === "context" ? "failed"
          : phase.phase_id === "review" ? "repairing"
            : phase.phase_id === "synthesis" ? "withheld"
              : phase.phase_id === "release" ? "failed"
                : phase.status;
        return { ...phase, status };
      }),
      steps: [
        plan.steps[0],
        {
          ...plan.steps[1],
          safe_label: "Radeon specialist",
          status: "degraded",
          route: "radeon_api_fallback",
          degradation_code: "primary_route_unavailable",
          safe_summary: "The authorized fallback returned a bounded subset."
        },
        {
          ...plan.steps[1],
          step_id: "context-02",
          safe_label: "Local specialist",
          status: "failed",
          route: "local_rocm",
          failure_code: "model_unavailable",
          safe_summary: "The local specialist stopped safely."
        },
        {
          ...plan.steps[1],
          step_id: "review-01",
          parent_phase_id: "review",
          phase: "review",
          kind: "review",
          safe_label: "Evidence review",
          role_id: "evidence-critic/v1",
          status: "repairing",
          route: "local_rocm",
          safe_summary: "The reviewer requested one bounded repair."
        },
        {
          ...plan.steps[2],
          status: "withheld",
          failure_code: "evidence_rejected",
          safe_summary: "The final answer was withheld."
        }
      ]
    };
    render(
      <LiveExecutionPlan
        plan={exceptional}
        running={false}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    expect(screen.getAllByText("Radeon Api Fallback").length).toBeGreaterThan(0);
    expect(screen.getByText("Primary Route Unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Local Radeon inference").length).toBeGreaterThan(0);
    expect(screen.getByText("Model Unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Repairing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Withheld").length).toBeGreaterThan(0);
    expect(screen.getByText("Evidence Rejected")).toBeInTheDocument();
  });

  it("expands checklist proof independently from its parent step", () => {
    render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    const phase = screen.getByLabelText("Interpretation phase");
    fireEvent.click(phase.querySelector("summary")!);
    const step = screen.getByLabelText("Interpret request step");
    fireEvent.click(step.querySelector("summary")!);
    const check = screen.getByText("Validate request contract").closest("details")!;
    expect(check).not.toHaveAttribute("open");
    fireEvent.click(check.querySelector("summary")!);
    expect(check).toHaveAttribute("open");
    expect(screen.getByText("Request envelope accepted.")).toBeVisible();
    expect(screen.getByText("Contract authority · Required")).toBeVisible();
  });

  it("supports global disclosure controls and a limitation-focused view", () => {
    const degraded: ExecutionPlan = {
      ...plan,
      status: "degraded",
      degradation_summary: ["primary_route_unavailable"],
      phases: plan.phases.map((phase) => ({
        ...phase,
        status: phase.phase_id === "context" ? "degraded" : phase.status
      })),
      steps: plan.steps.map((step) => ({
        ...step,
        status: step.step_id === "context-01" ? "degraded" : step.status
      }))
    };
    render(
      <LiveExecutionPlan
        plan={degraded}
        running={false}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(screen.getByLabelText("Interpretation phase")).toHaveAttribute("open");
    expect(screen.getByLabelText("Interpret request step")).toHaveAttribute("open");

    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.getByLabelText("Interpretation phase")).not.toHaveAttribute("open");
    expect(screen.getByRole("button", { name: "Follow active" })).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: /Show limitations/ }));
    expect(screen.getByLabelText("Context phase")).toBeInTheDocument();
    expect(screen.queryByLabelText("Interpretation phase")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Execution limitations")).toHaveTextContent("Primary Route Unavailable");
  });

  it("preserves manual expansion when a newer signed snapshot arrives for the same run", () => {
    const { rerender } = render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    const interpretation = screen.getByLabelText("Interpretation phase");
    fireEvent.click(interpretation.querySelector("summary")!);
    expect(interpretation).toHaveAttribute("open");

    rerender(
      <LiveExecutionPlan
        plan={{ ...plan, last_sequence: 4, projection_sha256: "b".repeat(64) }}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    expect(screen.getByLabelText("Interpretation phase")).toHaveAttribute("open");
  });

  it("shows governed interpretation depth, entities, as-of boundary, and clarification limits", () => {
    const interpreted: ExecutionPlan = {
      ...plan,
      steps: plan.steps.map((step) => step.step_id === "interpret-request" ? {
        ...step,
        checklist: [
          {
            check_id: "intent-boundary",
            label: "Classify governed intent",
            status: "passed",
            authority: "contract",
            required: true,
            safe_detail: "Primary intent: Company Comparison."
          },
          {
            check_id: "scope-boundary",
            label: "Resolve research scope",
            status: "passed",
            authority: "contract",
            required: true,
            reference_ids: ["company-msft", "company-googl"],
            safe_detail: "2 resolved entities with an as-of boundary of 2026-07-26."
          },
          {
            check_id: "ambiguity-boundary",
            label: "Preserve ambiguity boundary",
            status: "passed",
            authority: "contract",
            required: false,
            safe_detail: "Answer depth Deep; 0 declared ambiguities and 3 requested outputs were preserved."
          }
        ]
      } : step)
    };
    render(
      <LiveExecutionPlan
        plan={interpreted}
        running={false}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    const phase = screen.getByLabelText("Interpretation phase");
    fireEvent.click(phase.querySelector("summary")!);
    const step = screen.getByLabelText("Interpret request step");
    fireEvent.click(step.querySelector("summary")!);
    for (const label of [
      "Classify governed intent",
      "Resolve research scope",
      "Preserve ambiguity boundary"
    ]) {
      const row = screen.getByText(label).closest("details")!;
      fireEvent.click(row.querySelector("summary")!);
    }
    expect(screen.getByText("Primary intent: Company Comparison.")).toBeVisible();
    expect(screen.getByText(/as-of boundary of 2026-07-26/)).toBeVisible();
    expect(screen.getByText(/Answer depth Deep/)).toBeVisible();
  });

  it("withholds planning visibly when clarification is required", () => {
    const clarification: ExecutionPlan = {
      ...plan,
      status: "failed",
      terminal_steps: 2,
      progress_ratio: 2 / 3,
      phases: plan.phases.map((phase) => {
        if (phase.phase_id === "interpretation") {
          return { ...phase, status: "withheld", safe_summary: "Clarification is required." };
        }
        if (phase.phase_id === "planning") {
          return { ...phase, status: "unavailable", step_ids: ["build-plan"], safe_summary: "Planning did not begin." };
        }
        return phase;
      }),
      steps: [
        {
          ...plan.steps[0],
          status: "withheld",
          failure_code: "clarification_required",
          safe_summary: "Clarification is required before a bounded research plan can begin.",
          checklist: [{
            check_id: "request-contract",
            label: "Validate request contract",
            status: "withheld",
            authority: "contract",
            required: true,
            safe_detail: "The request remains ambiguous across 1 governed boundary."
          }]
        },
        {
          ...plan.steps[0],
          step_id: "build-plan",
          parent_phase_id: "planning",
          phase: "planning",
          safe_label: "Build bounded plan",
          safe_objective: "Select authorized roles only after interpretation.",
          role_id: "research-orchestrator/v1",
          status: "unavailable",
          failure_code: "dependency_unavailable",
          safe_summary: "Planning did not begin because interpretation requires clarification."
        },
        ...plan.steps.slice(1)
      ]
    };
    render(
      <LiveExecutionPlan
        plan={clarification}
        running={false}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    expect(screen.getByLabelText("Interpretation phase")).toHaveAttribute("open");
    expect(screen.getByText("Clarification is required before a bounded research plan can begin.")).toBeVisible();
    expect(screen.getByLabelText("Planning phase")).toHaveAttribute("open");
    expect(screen.getByText("Planning did not begin because interpretation requires clarification.")).toBeVisible();
  });

  it("shows bounded retrieval facts and keeps local and Radeon routes distinct", () => {
    const contextPlan: ExecutionPlan = {
      ...plan,
      total_steps: 4,
      steps: [
        plan.steps[0],
        {
          ...plan.steps[1],
          route: "local_rocm",
          safe_summary: "The local specialist released a validated packet.",
          checklist: [{
            check_id: "retrieval-local",
            label: "Authorized evidence retrieval completed",
            status: "passed",
            authority: "retrieval",
            required: false,
            reference_ids: ["retrieval-local", "bundle-local"],
            safe_detail: "The validated packet contains 4 authorized evidence references across SEC filing source classes as of 2026-07-26; retrieval method RRF; 4 of 8 matched candidates selected and 4 rejected by the bounded rank."
          }]
        },
        {
          ...plan.steps[1],
          step_id: "context-02",
          safe_label: "Economics specialist",
          role_id: "economics-macro/v1",
          route: "radeon_api",
          safe_summary: "The Radeon Cloud specialist is compiling governed context.",
          checklist: [{
            check_id: "retrieval-remote",
            label: "Authorize remote evidence context",
            status: "running",
            authority: "retrieval",
            required: true,
            safe_detail: "The authorized retrieval provider is resolving bounded evidence."
          }]
        },
        plan.steps[2]
      ]
    };
    render(
      <LiveExecutionPlan
        plan={contextPlan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    const local = screen.getByLabelText("Accounting Reporting step");
    if (!local.hasAttribute("open")) {
      fireEvent.click(local.querySelector("summary")!);
    }
    const remote = screen.getByLabelText("Economics specialist step");
    if (!remote.hasAttribute("open")) {
      fireEvent.click(remote.querySelector("summary")!);
    }
    expect(screen.getByText("Local Radeon inference")).toBeVisible();
    expect(screen.getByText("Radeon Cloud specialist")).toBeVisible();
    const retrieval = screen.getByText("Authorized evidence retrieval completed").closest("details")!;
    fireEvent.click(retrieval.querySelector("summary")!);
    expect(screen.getByText(/retrieval method RRF/)).toBeVisible();
    expect(screen.getByText(/4 of 8 matched candidates selected/)).toBeVisible();
  });

  it.each([
    ["skipped", "The session is ephemeral; no research case was retained."],
    ["running", "The user explicitly requested local research-case retention."],
    ["passed", "The user-approved research case was saved locally."],
    ["unavailable", "Local retention was requested, but no case store was available."],
    ["degraded", "Research completed, but the requested local save failed."],
    ["passed", "The saved local research case was deleted at the user's request."]
  ] as const)("shows the explicit memory lifecycle for %s", (status, summary) => {
    const memoryPlan: ExecutionPlan = {
      ...plan,
      phases: plan.phases.map((phase) => phase.phase_id === "memory" ? {
        ...phase,
        status,
        step_ids: ["memory-retention"],
        safe_summary: summary
      } : phase),
      steps: [...plan.steps, {
        step_id: "memory-retention",
        parent_phase_id: "memory",
        phase: "memory",
        kind: "memory",
        safe_label: "Apply memory preference",
        safe_objective: "Honor the user's explicit local retention choice.",
        role_id: "final-research-analyst/v1",
        mandatory: false,
        status,
        checklist: [{
          check_id: "retention-policy",
          label: "Apply opt-in retention policy",
          status,
          authority: "runtime",
          required: false,
          safe_detail: summary
        }],
        attempt: 1,
        max_attempts: 1,
        safe_summary: summary
      }]
    };
    render(
      <LiveExecutionPlan
        plan={memoryPlan}
        running={status === "running"}
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );

    const phase = screen.getByLabelText("Memory phase");
    if (!phase.hasAttribute("open")) {
      fireEvent.click(phase.querySelector("summary")!);
    }
    const step = screen.getByLabelText("Apply memory preference step");
    if (!step.hasAttribute("open")) {
      fireEvent.click(step.querySelector("summary")!);
    }
    expect(screen.getAllByText(summary).length).toBeGreaterThan(0);
    expect(screen.getByText("Runtime authority · Supporting")).toBeInTheDocument();
  });

  it("preserves manual disclosure state across a high-frequency signed snapshot burst", () => {
    const { rerender } = render(
      <LiveExecutionPlan
        plan={plan}
        running
        onProof={vi.fn()}
        onCalculations={vi.fn()}
        onLineage={vi.fn()}
      />
    );
    const interpretation = screen.getByLabelText("Interpretation phase");
    fireEvent.click(interpretation.querySelector("summary")!);
    const interpretationStep = screen.getByLabelText("Interpret request step");
    fireEvent.click(interpretationStep.querySelector("summary")!);

    for (let sequence = 4; sequence <= 103; sequence += 1) {
      rerender(
        <LiveExecutionPlan
          plan={{
            ...plan,
            last_sequence: sequence,
            projection_sha256: sequence.toString(16).padStart(64, "0")
          }}
          running
          onProof={vi.fn()}
          onCalculations={vi.fn()}
          onLineage={vi.fn()}
        />
      );
    }

    expect(screen.getByLabelText("Interpretation phase")).toHaveAttribute("open");
    expect(screen.getByLabelText("Interpret request step")).toHaveAttribute("open");
  });
});
