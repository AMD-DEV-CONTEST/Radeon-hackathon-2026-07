import { describe, expect, it } from "vitest";
import type { OutcomeCandidate, SessionStore } from "airecap-plus";
import { buildStructuredReport, renderReportMarkdown } from "../src/report.js";

function oc(partial: Partial<OutcomeCandidate> & Pick<OutcomeCandidate, "id" | "title" | "status">): OutcomeCandidate {
  return {
    session_id: "t1",
    type: "feature",
    confidence: 0.5,
    confidence_raw: 0.5,
    clamp_reason: "none",
    evidence_links: [],
    counter_evidence: [],
    scope: { paths: [], symbols: [], services: [], commands: [] },
    started_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    merge_of: [],
    aggregator_version: "rules@1.2",
    summary_blob: "",
    tags: [],
    verification_anchors: [],
    ...partial,
  };
}

function store(outcomes: OutcomeCandidate[]): SessionStore {
  return {
    schema_version: "s/1.0",
    session_id: "t1",
    aggregator_version: "rules@1.2",
    status: "open",
    started_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    goals: [],
    outcomes,
    orphan_event_ids: [],
    counters: { events_seen: 0, high_signal_seen: 0 },
    constants: {} as SessionStore["constants"],
  };
}

describe("report gates", () => {
  it("does not list claimed-only items under 成果", () => {
    const report = buildStructuredReport({
      store: store([
        oc({
          id: "o1",
          title: "假完成",
          type: "feature",
          status: "claimed",
          confidence: 0.2,
        }),
        oc({
          id: "o2",
          title: "真修好",
          type: "bugfix",
          status: "verified",
          confidence: 0.9,
          scope: {
            paths: ["src/auth.py"],
            symbols: [],
            services: [],
            commands: ["pytest"],
          },
          verification_anchors: [{ kind: "test", key: "tests/test_auth.py::test_x" }],
        }),
      ]),
    });
    expect(report.summary.verified).toBe(1);
    expect(report.summary.claimed).toBe(1);
    const md = renderReportMarkdown(report);
    expect(md).toContain("真修好");
    expect(md).toMatch(/门禁|拒绝未验证/);
    const doneSection = md.split("## 代码证据")[0] ?? "";
    expect(doneSection).toContain("真修好");
    expect(doneSection).not.toContain("假完成");
    expect(md).toContain("未闭合");
  });
});
