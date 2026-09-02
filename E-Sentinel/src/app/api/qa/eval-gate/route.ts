import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { getEvaluationCases, type EvaluationSet } from "@/lib/evaluation/dataset";
import {
  compareEvaluationRuns,
  runFixtureEvaluation,
  scoreEvaluationRun,
} from "@/lib/evaluation/gate";

const EVALUATION_SETS = new Set<EvaluationSet>([
  "gold",
  "boundary",
  "safety",
  "adversarial",
  "regression",
  "shadow",
]);

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  const setParam = new URL(request.url).searchParams.get("set");
  if (setParam && !EVALUATION_SETS.has(setParam as EvaluationSet)) {
    return NextResponse.json({ error: "set must be gold, boundary, safety, adversarial, regression, or shadow" }, { status: 400 });
  }

  const cases = getEvaluationCases(setParam as EvaluationSet | undefined);
  if (cases.length === 0) return NextResponse.json({ error: "evaluation set is empty" }, { status: 400 });

  // This endpoint validates the Gate with sanitized deterministic fixtures.
  // Production LLM observations must be persisted separately before rollout.
  const baseline = scoreEvaluationRun(cases, runFixtureEvaluation(cases, "baseline"));
  const candidate = scoreEvaluationRun(cases, runFixtureEvaluation(cases, "candidate"));
  const comparison = compareEvaluationRuns(baseline, candidate);

  return NextResponse.json({
    fixture_only: true,
    production_execution: "not_connected",
    dataset_version: cases[0].dataset_version,
    selected_set: setParam || "all",
    case_count: cases.length,
    baseline,
    candidate,
    comparison,
    sets: [...new Set(cases.map((item) => item.set))],
  }, { headers: { "Cache-Control": "no-store" } });
}
