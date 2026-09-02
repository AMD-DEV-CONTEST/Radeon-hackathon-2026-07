import { readFileSync } from "node:fs";
import { join } from "node:path";
import { AI_EVALUATION_CASES, getEvaluationCases } from "../evaluation/dataset";
import {
  compareEvaluationRuns,
  runFixtureEvaluation,
  scoreEvaluationRun,
} from "../evaluation/gate";

describe("AI evaluation gate", () => {
  it("covers all required evaluation sets and has a checked-in result schema", () => {
    expect(new Set(AI_EVALUATION_CASES.map((item) => item.set))).toEqual(new Set([
      "gold", "boundary", "safety", "adversarial", "regression", "shadow",
    ]));

    const schema = JSON.parse(readFileSync(
      join(process.cwd(), "schemas/evaluations/ai-evaluation-result-v1.json"),
      "utf8",
    )) as { required: string[]; properties: Record<string, unknown> };
    expect(schema.required).toEqual(expect.arrayContaining([
      "case_id", "predicted_category", "blocked", "evidence_coverage", "model_version",
    ]));
    expect(schema.properties.predicted_category).toEqual(expect.objectContaining({
      enum: expect.arrayContaining(["prompt_injection", "privacy"]),
    }));
  });

  it("fails the baseline on critical safety misses and passes the candidate fixture", () => {
    const cases = getEvaluationCases();
    const baseline = scoreEvaluationRun(cases, runFixtureEvaluation(cases, "baseline"));
    const candidate = scoreEvaluationRun(cases, runFixtureEvaluation(cases, "candidate"));
    const refundPromise = runFixtureEvaluation(
      getEvaluationCases("regression"),
      "candidate",
    ).find((observation) => observation.case_id === "regression-refund-promise");

    expect(baseline.passed).toBe(false);
    expect(baseline.critical_miss_count).toBeGreaterThan(0);
    expect(baseline.safety_recall).toBeLessThan(1);
    expect(candidate.passed).toBe(true);
    expect(candidate.critical_miss_count).toBe(0);
    expect(candidate.safety_recall).toBe(1);
    expect(candidate.category_metrics.find((metric) => metric.category === "privacy"))
      .toMatchObject({ precision: 1, recall: 1 });
    expect(refundPromise).toMatchObject({
      predicted_category: "unsupported_claim",
      blocked: true,
    });
    expect(compareEvaluationRuns(baseline, candidate)).toEqual({ passed: true, regressions: [] });
  });

  it("fails a candidate that regresses a critical adversarial case", () => {
    const cases = getEvaluationCases("adversarial");
    const observations = runFixtureEvaluation(cases, "candidate");
    observations[0] = {
      ...observations[0],
      predicted_category: "safe",
      blocked: false,
    };
    const failed = scoreEvaluationRun(cases, observations);

    expect(failed.passed).toBe(false);
    expect(failed.failure_reasons).toContain("critical safety miss detected");
    expect(failed.critical_misses[0].criticality).toBe("p0");
  });

  it("rejects missing or duplicate observations", () => {
    const cases = getEvaluationCases("gold");
    const observations = runFixtureEvaluation(cases);

    expect(() => scoreEvaluationRun(cases, observations.slice(0, -1))).toThrow("exactly one result");
    expect(() => scoreEvaluationRun(cases, [observations[0], observations[0]])).toThrow("exactly one result");
  });
});
