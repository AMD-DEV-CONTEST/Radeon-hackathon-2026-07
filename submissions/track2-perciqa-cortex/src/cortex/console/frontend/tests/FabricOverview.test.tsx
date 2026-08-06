import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { FabricOverview } from "../src/views/FabricOverview";

function activity(id: string, agent: string, step: string) {
  return {
    id,
    type: "activity" as const,
    content: "",
    payload: { agent_name: agent, activity_step: step },
  };
}

function renderOverview(activities: ReturnType<typeof activity>[]) {
  return render(
    <FabricOverview
      articles={[]}
      activities={activities}
      byNode={{}}
      connected
      attackCounts={{}}
      onNavigate={() => {}}
    />
  );
}

describe("FabricOverview agents summary", () => {
  it("renders the separator as a middle dot, not a literal escape", () => {
    const { container } = renderOverview([
      activity("a1", "SOC Alpha", "completed"),
    ]);
    const summary = container.textContent || "";
    expect(summary).toContain("\u00b7");
    expect(summary).not.toContain("\\u00b7");
  });

  it("shows the newest activity step per agent, not the oldest", () => {
    // The reducer stores activities newest-first: index 0 is the newest.
    const activities = [
      activity("a4", "SOC Alpha", "completed"),
      activity("a3", "SOC Alpha", "publishing"),
      activity("a2", "SOC Alpha", "reasoning"),
      activity("a1", "SOC Alpha", "querying"),
    ];
    const { container } = renderOverview(activities);
    const summary = container.textContent || "";
    expect(summary).toContain("4 events");
    // The agent row should reflect the newest step (completed), not the oldest (querying).
    expect(summary).toContain("completed");
  });

  it("collapses consecutive reasoning activities into one reasoning pass", () => {
    // A single cycle emits two consecutive "reasoning" activities (start + complete).
    const activities = [
      activity("a4", "SOC Alpha", "completed"),
      activity("a3", "SOC Alpha", "reasoning"),
      activity("a2", "SOC Alpha", "reasoning"),
      activity("a1", "SOC Alpha", "querying"),
    ];
    const { container } = renderOverview(activities);
    expect(container.textContent).toContain("1 reasoning");
  });

  it("counts two separate reasoning passes across cycles", () => {
    const activities = [
      activity("a8", "SOC Alpha", "completed"),
      activity("a7", "SOC Alpha", "reasoning"),
      activity("a6", "SOC Alpha", "reasoning"),
      activity("a5", "SOC Alpha", "querying"),
      activity("a4", "SOC Alpha", "completed"),
      activity("a3", "SOC Alpha", "reasoning"),
      activity("a2", "SOC Alpha", "reasoning"),
      activity("a1", "SOC Alpha", "querying"),
    ];
    const { container } = renderOverview(activities);
    expect(container.textContent).toContain("2 reasoning");
  });
});
