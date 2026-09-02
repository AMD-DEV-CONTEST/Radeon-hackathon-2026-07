import { describe, expect, it } from "vitest";

import {
  DETERMINEX_INDUSTRY_BACKLOG_CATEGORIES,
  DETERMINEX_INDUSTRY_IDE_BACKLOG,
  getIndustryIdeBacklogSummary,
  getIndustryIdeCategorySummary,
  getTopIndustryIdeNextActions,
  isIndustryBacklogItemChecked,
} from "../industryIdeBacklog";

describe("industry IDE backlog", () => {
  it("tracks the full industry checklist without granting blanket completion", () => {
    const summary = getIndustryIdeBacklogSummary();

    expect(DETERMINEX_INDUSTRY_IDE_BACKLOG).toHaveLength(82);
    expect(summary.total).toBe(82);
    expect(summary.checked).toBeLessThan(summary.total);
    expect(summary.blocked).toBeGreaterThan(0);
    expect(summary.partial).toBeGreaterThan(0);
  });

  it("requires evidence for every checked or partial item and blockers for every blocked item", () => {
    for (const item of DETERMINEX_INDUSTRY_IDE_BACKLOG) {
      expect(item.nextAction.length).toBeGreaterThan(12);
      if (item.status === "done" || item.status === "partial") {
        expect(item.evidence.length).toBeGreaterThan(0);
      }
      if (item.status === "blocked") {
        expect(item.blocker.length).toBeGreaterThan(12);
      }
      if (isIndustryBacklogItemChecked(item)) {
        expect(item.status).toBe("done");
        expect(item.blocker).toBe("");
      }
    }
  });

  it("keeps every category represented by at least one checklist item", () => {
    for (const category of DETERMINEX_INDUSTRY_BACKLOG_CATEGORIES) {
      const summary = getIndustryIdeCategorySummary(category.id);
      expect(summary.total).toBeGreaterThan(0);
    }
  });

  it("prioritizes unfinished P0 blockers as the next actions", () => {
    const nextActions = getTopIndustryIdeNextActions(5);

    expect(nextActions).toHaveLength(5);
    expect(nextActions.every((item) => item.priority === "P0")).toBe(true);
    expect(nextActions[0].status).toBe("blocked");
    expect(nextActions.every((item) => !isIndustryBacklogItemChecked(item))).toBe(true);
  });
});
