import { createReleaseManifest, transitionFeedback, verifyReleaseManifest, type FeedbackRecord } from "../governance/feedback-lifecycle";

const captured: FeedbackRecord = {
  feedbackId: "fb-1", sourceTraceId: "trace-1", status: "captured", owner: "reviewer-a",
  linkedDatasetItems: [], regressionPassed: false, updatedAt: "2026-07-27T00:00:00.000Z",
};

describe("feedback lifecycle", () => {
  it("only permits the audited lifecycle and requires root cause, regression and approval", () => {
    expect(() => transitionFeedback(captured, "released", "reviewer-a")).toThrow("invalid feedback transition");
    const triaged = transitionFeedback(captured, "triaged", "reviewer-a");
    expect(() => transitionFeedback(triaged, "accepted", "reviewer-a")).toThrow("reasonCode");
    const accepted = transitionFeedback({ ...triaged, reasonCode: "RULE_MISSING" }, "accepted", "reviewer-a");
    const drafted = transitionFeedback(accepted, "change_drafted", "engineer-a");
    const running = transitionFeedback(drafted, "regression_running", "engineer-a");
    expect(() => transitionFeedback(running, "approved", "reviewer-a")).toThrow("passing regression");
  });

  it("requires an immutable, complete manifest for a release claim", () => {
    const manifest = createReleaseManifest({
      releaseId: "contest-demo-v1.1", commitSha: "a1b2c3d", deploymentId: "preview-1", model: "fixed-demo", promptVersion: "qa-demo-v1", ruleSetVersion: "demo-rules-2026.07", datasetVersion: "qa-gold-v1", schemaVersion: "qa-decision-v1", evaluationReport: "reports/contest-demo-v1.1.json", regressionPassed: true, approvedBy: "reviewer-a", releasedAt: "2026-07-27T00:00:00.000Z",
    });
    expect(verifyReleaseManifest(manifest)).toBe(true);
    expect(verifyReleaseManifest({ ...manifest, datasetVersion: "changed" })).toBe(false);
    expect(() => createReleaseManifest({
      releaseId: "contest-demo-v1.2", commitSha: "a1b2c3d", deploymentId: "preview-2", model: "fixed-demo", promptVersion: "qa-demo-v1", ruleSetVersion: "demo-rules-2026.07", datasetVersion: "qa-gold-v1", schemaVersion: "qa-decision-v1", evaluationReport: "reports/contest-demo-v1.2.json", regressionPassed: false, approvedBy: "reviewer-a", releasedAt: "2026-07-27T00:00:00.000Z",
    })).toThrow("passing regression");
  });
});
