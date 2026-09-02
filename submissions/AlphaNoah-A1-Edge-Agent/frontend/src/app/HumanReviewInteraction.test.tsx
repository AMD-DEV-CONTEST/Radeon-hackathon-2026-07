import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { adaptDigitalEmployeeCollection } from "../features/digital-employees/adapter/digitalEmployeeAdapter";
import type { DigitalEmployeeDataSource } from "../features/digital-employees";
import {
  HumanReviewError,
  type HumanReviewDataSource,
  type HumanReviewSnapshot,
} from "../features/human-review";
import { adaptWorkspaceProjection } from "../features/runtime/adapter/workspaceProjectionAdapter";
import {
  mockProviderRuntimeDataSource,
} from "../features/runtime/composition";
import type {
  PulseDataSource,
  WorkspaceDataSource,
} from "../features/runtime";
import {
  PREFERENCES_STORAGE_KEY,
} from "../preferences/preferences";
import { App } from "./App";

const eventId = "event_0123456789abcdef0123456789abcdef";
const decisionId = "decision_0123456789abcdef0123456789abcdef";
const taskId = "task_0123456789abcdef0123456789abcdef";

describe("F04-B Human Review interaction", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "en-US",
        theme: "dark",
        motion: "reduced",
      }),
    );
  });

  it("shows pending AI recommendation and linked employee", async () => {
    const harness = new HumanReviewHarness();
    const user = userEvent.setup();
    renderApp(harness);

    await openReview(user);

    expect(
      await screen.findByText("Waiting for human decision"),
    ).toBeInTheDocument();
    expect(screen.getByText("Room A08 air conditioner remained on")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("Equipment Maintenance Agent")).toBeInTheDocument();
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("waits for approval and displays the persisted Task", async () => {
    const harness = new HumanReviewHarness();
    const user = userEvent.setup();
    renderApp(harness);
    await openReview(user);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(screen.getAllByText("Task created")).not.toHaveLength(0);
    expect(screen.getByText("Working · task created")).toBeInTheDocument();
    expect(harness.approveCalls).toBe(1);
    await waitFor(() => expect(harness.workspaceReads).toBeGreaterThan(1));
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("disables both decisions during one in-flight approval", async () => {
    const harness = new HumanReviewHarness();
    const release = harness.delayApproval();
    const user = userEvent.setup();
    renderApp(harness);
    await openReview(user);

    const approval = user.dblClick(
      screen.getByRole("button", { name: "Approve" }),
    );

    await waitFor(() => expect(harness.approveCalls).toBe(1));
    expect(
      screen.getAllByRole("button", { name: "Submitting…" }),
    ).toHaveLength(2);
    for (const button of screen.getAllByRole("button", {
      name: "Submitting…",
    })) {
      expect(button).toBeDisabled();
    }

    release();
    await approval;
    expect(await screen.findAllByText("Task created")).not.toHaveLength(0);
    expect(harness.approveCalls).toBe(1);
  });

  it("records rejection and shows that no action executed", async () => {
    const harness = new HumanReviewHarness();
    const user = userEvent.setup();
    renderApp(harness);
    await openReview(user);

    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(await screen.findAllByText("Rejected")).not.toHaveLength(0);
    expect(screen.getByText("No action executed")).toBeInTheDocument();
    expect(harness.rejectCalls).toBe(1);
  });

  it("disables both decisions during one in-flight rejection", async () => {
    const harness = new HumanReviewHarness();
    const release = harness.delayRejection();
    const user = userEvent.setup();
    renderApp(harness);
    await openReview(user);

    const rejection = user.dblClick(
      screen.getByRole("button", { name: "Reject" }),
    );

    await waitFor(() => expect(harness.rejectCalls).toBe(1));
    expect(
      screen.getAllByRole("button", { name: "Submitting…" }),
    ).toHaveLength(2);
    release();
    await rejection;
    expect(await screen.findAllByText("Rejected")).not.toHaveLength(0);
    expect(harness.rejectCalls).toBe(1);
  });

  it("keeps the pending state when Runtime rejects the action", async () => {
    const harness = new HumanReviewHarness();
    harness.failAction = true;
    const user = userEvent.setup();
    renderApp(harness);
    await openReview(user);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText(
        "The Runtime did not confirm this action. Refresh before trying again.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting for human decision")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("recovers approved state from Runtime after a page remount", async () => {
    const harness = new HumanReviewHarness("approved");
    const user = userEvent.setup();
    const first = renderApp(harness);
    await openReview(user);
    expect(await screen.findAllByText("Task created")).not.toHaveLength(0);

    first.unmount();
    window.history.replaceState({}, "", "/");
    renderApp(harness);
    await openReview(userEvent.setup());

    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(screen.getAllByText("Task created")).not.toHaveLength(0);
    expect(harness.reviewReads).toBe(2);
  });

  it("localizes rejected machine status in the Chinese UI", async () => {
    window.localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        locale: "zh-CN",
        theme: "dark",
        motion: "reduced",
      }),
    );
    const harness = new HumanReviewHarness("rejected");
    renderApp(harness);
    await openReview(userEvent.setup());

    expect(await screen.findAllByText("已拒绝")).not.toHaveLength(0);
    expect(screen.queryByText("REJECTED")).not.toBeInTheDocument();
  });
});

class HumanReviewHarness implements HumanReviewDataSource {
  state: "pending" | "approved" | "rejected";
  failAction = false;
  reviewReads = 0;
  approveCalls = 0;
  rejectCalls = 0;
  workspaceReads = 0;
  private approvalGate: Promise<void> | null = null;
  private releaseApproval: (() => void) | null = null;
  private rejectionGate: Promise<void> | null = null;
  private releaseRejection: (() => void) | null = null;

  constructor(state: "pending" | "approved" | "rejected" = "pending") {
    this.state = state;
  }

  getReview = async (): Promise<HumanReviewSnapshot> => {
    this.reviewReads += 1;
    return this.snapshot();
  };

  approve = async (): Promise<HumanReviewSnapshot> => {
    this.approveCalls += 1;
    await this.approvalGate;
    if (this.failAction) {
      throw new HumanReviewError("rejected", "Review rejected.");
    }
    this.state = "approved";
    return this.snapshot();
  };

  reject = async (): Promise<HumanReviewSnapshot> => {
    this.rejectCalls += 1;
    await this.rejectionGate;
    this.state = "rejected";
    return this.snapshot();
  };

  createTask = async (): Promise<HumanReviewSnapshot> => {
    this.state = "approved";
    return this.snapshot();
  };

  delayApproval(): () => void {
    this.approvalGate = new Promise((resolve) => {
      this.releaseApproval = resolve;
    });
    return () => this.releaseApproval?.();
  }

  delayRejection(): () => void {
    this.rejectionGate = new Promise((resolve) => {
      this.releaseRejection = resolve;
    });
    return () => this.releaseRejection?.();
  }

  workspace: WorkspaceDataSource = {
    source: "http",
    getInitialSnapshot: () => this.workspaceSnapshot(),
    getWorkspace: async () => {
      this.workspaceReads += 1;
      return this.workspaceSnapshot();
    },
  };

  employees: DigitalEmployeeDataSource = {
    source: "http",
    getInitialCollection: () => this.employeeCollection(),
    getEmployees: async () => this.employeeCollection(),
  };

  pulse: PulseDataSource = {
    source: "http",
    getInitialPulse: () => null,
    getPulse: async () => null,
  };

  private snapshot(): HumanReviewSnapshot {
    return {
      eventId,
      eventStatus:
        this.state === "pending"
          ? "PENDING_HUMAN_REVIEW"
          : this.state === "approved"
            ? "TASK_CREATED"
            : "REJECTED",
      state: this.state,
      analysis: {
        finding: "Room A08 air conditioner remained on",
        analysis: "No occupancy was reported after closing.",
        recommendation:
          "Verify occupancy, then use the approved shutdown procedure",
        confidence: 0.85,
        severity: "HIGH",
      },
      decision: {
        id: decisionId,
        status:
          this.state === "pending"
            ? "PENDING_HUMAN_REVIEW"
            : this.state.toUpperCase(),
        requiresHumanReview: true,
      },
      task:
        this.state === "approved"
          ? {
              id: taskId,
              status: "CREATED",
              owner: "demo:restaurant-duty-operator",
            }
          : null,
      timelineCount: this.state === "pending" ? 4 : 6,
    };
  }

  private workspaceSnapshot() {
    const event = {
      id: eventId,
      type: "device_not_shutdown",
      status:
        this.state === "pending"
          ? "PENDING_HUMAN_REVIEW"
          : this.state === "approved"
            ? "TASK_CREATED"
            : "REJECTED",
      timestamp: "2026-08-01T10:35:00+08:00",
      severity: "HIGH" as const,
      location: "B03",
      asset_id: "B03-AIRCON",
      description: "Cooling performance is weaker than normal.",
      responsibility: {
        id: "equipment-maintenance",
        name: "Equipment Maintenance",
      },
    };
    return adaptWorkspaceProjection({
      version: "workspace-v1",
      events: [event],
      active_event: this.state === "rejected" ? null : event,
      pulse: null,
      employees: [],
    });
  }

  private employeeCollection() {
    return adaptDigitalEmployeeCollection([
      {
        id: "equipment-maintenance",
        name: "Equipment Maintenance Agent",
        status: this.state === "rejected" ? "unknown" : "working",
        current_event_id: this.state === "rejected" ? null : eventId,
        responsibility: "Equipment anomaly analysis",
        skills: [{ name: "Anomaly analysis" }],
      },
    ]);
  }
}

function renderApp(harness: HumanReviewHarness) {
  return render(
    <App
      digitalEmployeeDataSource={harness.employees}
      humanReviewDataSource={harness}
      pulseDataSource={harness.pulse}
      providerRuntimeDataSource={mockProviderRuntimeDataSource}
      workspaceDataSource={harness.workspace}
    />,
  );
}

async function openReview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", {
      name: /device_not_shutdown/,
    }),
  );
}
