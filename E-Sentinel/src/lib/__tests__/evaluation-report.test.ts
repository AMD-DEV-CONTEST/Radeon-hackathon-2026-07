import { AI_EVALUATION_DATASET_VERSION, getEvaluationCases } from "../evaluation/dataset";
import { runFixtureEvaluation, scoreEvaluationRun } from "../evaluation/gate";
import { buildEvaluationReport } from "../evaluation/report";

describe("evaluation report", () => {
  it("keeps the checked-in run explicitly fixture-only", () => {
    const cases = getEvaluationCases();
    const observations = runFixtureEvaluation(cases, "candidate");
    const score = scoreEvaluationRun(cases, observations);
    const report = buildEvaluationReport(score, { cases, observations });

    expect(report.fixture_only).toBe(true);
    expect(report.human_gold).toBe(false);
    expect(report.source).toBe("fixture-only");
    expect(report.dataset_version).toBe(AI_EVALUATION_DATASET_VERSION);
    expect(report.sample_count).toBe(cases.length);
    expect(report.denominators.samples).toBe(cases.length);
    expect(report.critical_recall).toMatchObject({ numerator: 6, denominator: 6, rate: 1 });
    expect(report.failure_case_ids).toEqual([]);
  });

  it("reports denominators and failed case IDs for a regressed fixture", () => {
    const cases = getEvaluationCases("adversarial");
    const observations = runFixtureEvaluation(cases, "candidate");
    observations[0] = { ...observations[0], predicted_category: "safe", blocked: false };
    const score = scoreEvaluationRun(cases, observations);
    const report = buildEvaluationReport(score, { cases, observations });

    expect(report.sample_count).toBe(2);
    expect(report.denominators.critical).toBe(2);
    expect(report.critical_recall).toEqual({ numerator: 1, denominator: 2, rate: 0.5 });
    expect(report.failure_case_ids).toContain("adversarial-direct-injection");
    expect(report.false_negative_count).toBeGreaterThan(0);
    expect(report.latency.p95_ms).toBe(score.p95_latency_ms);
    expect(report.cost.total).toBeCloseTo(score.average_cost * score.sample_count, 6);
  });

  it("cannot promote fixture cases to human Gold by changing a caller flag", () => {
    const cases = getEvaluationCases();
    const observations = runFixtureEvaluation(cases, "candidate");
    const score = scoreEvaluationRun(cases, observations);
    expect(buildEvaluationReport(score, { cases, observations, source: "human-gold" })).toMatchObject({ fixture_only: true, human_gold: false, source: "fixture-only" });
  });
});
