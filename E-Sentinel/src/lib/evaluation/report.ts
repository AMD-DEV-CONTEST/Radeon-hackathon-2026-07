import type {
  EvaluationCase,
  EvaluationCriticality,
} from "./dataset";
import type {
  CategoryMetric,
  EvaluationGateScore,
  EvaluationObservation,
} from "./gate";

export type EvaluationSource = "fixture-only" | "human-gold" | "mixed";

export interface EvaluationReportOptions {
  /** Cases and observations are optional because a persisted gate score is sufficient for class metrics. */
  cases?: readonly EvaluationCase[];
  observations?: readonly EvaluationObservation[];
  model_version?: string;
  prompt_version?: string;
  rule_version?: string;
  dataset_version?: string;
  source?: EvaluationSource;
  /** Human Gold provenance must be independently attested; never infer it from case labels. */
  human_gold_verified?: boolean;
  /** Explicit denominators are useful when a score was persisted without its case rows. */
  risk_denominators?: {
    high?: number;
    critical?: number;
  };
}

export interface EvaluationReportMetric {
  numerator: number;
  denominator: number;
  rate: number;
}

export interface EvaluationReport {
  report_version: "evaluation-report-v1";
  source: EvaluationSource;
  fixture_only: boolean;
  human_gold: boolean;
  sample_count: number;
  denominators: {
    samples: number;
    high_risk: number;
    critical: number;
    false_negatives: number;
  };
  accuracy: EvaluationReportMetric;
  high_recall: EvaluationReportMetric;
  critical_recall: EvaluationReportMetric;
  high_critical_recall: EvaluationReportMetric;
  /** Alias retained for consumers that call p1/p0 by their severity names. */
  high_risk_recall: number | null;
  false_negative_rate: number;
  false_negative_count: number;
  per_class_metrics: Array<CategoryMetric & { denominator: number }>;
  /** Compatibility aliases for callers consuming the gate's flat names. */
  category_metrics: Array<CategoryMetric & { denominator: number }>;
  evidence_coverage: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  average_cost: number;
  latency: {
    p50_ms: number;
    p95_ms: number;
  };
  cost: {
    average: number;
    total: number;
  };
  model_version: string;
  prompt_version: string;
  rule_version: string;
  dataset_version: string;
  versions: {
    model: string;
    prompt: string;
    rule: string;
    dataset: string;
  };
  failure_case_ids: string[];
  /** Same IDs under the shorter name used by the gate result. */
  failed_case_ids: string[];
  failure_reasons: string[];
}

function rate(numerator: number, denominator: number): number {
  if (denominator === 0) return 0;
  return Math.round((numerator / denominator) * 10_000) / 10_000;
}

function finite(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

function metric(numerator: number, denominator: number): EvaluationReportMetric {
  return { numerator, denominator, rate: rate(numerator, denominator) };
}

function observationMap(observations: readonly EvaluationObservation[] | undefined): Map<string, EvaluationObservation> {
  return new Map((observations || []).map((observation) => [observation.case_id, observation]));
}

function riskRecall(
  cases: readonly EvaluationCase[] | undefined,
  observations: Map<string, EvaluationObservation>,
  criticality: EvaluationCriticality,
  explicitDenominator?: number,
  criticalMissIds: ReadonlySet<string> = new Set(),
): EvaluationReportMetric {
  const riskCases = cases?.filter((item) => item.criticality === criticality) || [];
  const denominator = explicitDenominator ?? riskCases.length;
  if (!cases) return metric(denominator, denominator);
  const numerator = riskCases.filter((item) => {
    const observation = observations.get(item.case_id);
    if (!observation) return !criticalMissIds.has(item.case_id);
    return Boolean(observation && (!item.expected_block || (
      observation.blocked && observation.predicted_category === item.expected_category
    )));
  }).length;
  return metric(numerator, denominator);
}

function deriveFailureIds(
  score: EvaluationGateScore,
  cases: readonly EvaluationCase[] | undefined,
  observations: Map<string, EvaluationObservation>,
): string[] {
  const ids = new Set(score.critical_misses.map((item) => item.case_id));
  if (cases && observations.size > 0) {
    for (const evaluationCase of cases) {
      const observation = observations.get(evaluationCase.case_id);
      if (!observation) {
        ids.add(evaluationCase.case_id);
        continue;
      }
      const categoryMismatch = observation.predicted_category !== evaluationCase.expected_category;
      const blockMismatch = evaluationCase.expected_block !== observation.blocked;
      if (categoryMismatch || blockMismatch) ids.add(evaluationCase.case_id);
    }
  }
  return [...ids].sort();
}

/**
 * Build a deterministic, provenance-aware report. This function never upgrades
 * fixture labels to human Gold labels; callers must explicitly provide source.
 */
export function buildEvaluationReport(
  score: EvaluationGateScore,
  options: EvaluationReportOptions = {},
): EvaluationReport {
  const cases = options.cases;
  const observations = observationMap(options.observations);
  const firstObservation = options.observations?.[0];
  const requestedSource = options.source || "fixture-only";
  const source: EvaluationSource = requestedSource === "human-gold" && options.human_gold_verified === true
    ? "human-gold"
    : requestedSource === "mixed" && options.human_gold_verified === true
      ? "mixed"
      : "fixture-only";
  const failureCaseIds = deriveFailureIds(score, cases, observations);
  const criticalMissIds = new Set(score.critical_misses.map((item) => item.case_id));
  const high = riskRecall(cases, observations, "p1", options.risk_denominators?.high, criticalMissIds);
  const critical = riskRecall(cases, observations, "p0", options.risk_denominators?.critical, criticalMissIds);
  const highCriticalCases = cases?.filter((item) => item.criticality !== "none") || [];
  const highCritical = cases
    ? metric(
      highCriticalCases.filter((item) => !criticalMissIds.has(item.case_id) && (!observations.get(item.case_id)
        || (observations.get(item.case_id)?.blocked && observations.get(item.case_id)?.predicted_category === item.expected_category))).length,
      highCriticalCases.length,
    )
    : metric(0, 0);
  const falseNegativeCount = score.category_metrics.reduce((sum, item) => sum + item.false_negative, 0);
  const modelVersion = options.model_version || firstObservation?.model_version || "unknown";
  const promptVersion = options.prompt_version || firstObservation?.prompt_version || "unknown";
  const ruleVersion = options.rule_version || firstObservation?.rule_version || "unknown";
  const datasetVersion = options.dataset_version || cases?.[0]?.dataset_version || "unknown";
  const perClassMetrics = score.category_metrics.map((item) => ({ ...item, denominator: item.expected }));
  const totalCost = Math.round(finite(score.average_cost) * score.sample_count * 1_000_000) / 1_000_000;

  return {
    report_version: "evaluation-report-v1",
    source,
    fixture_only: source === "fixture-only",
    human_gold: source === "human-gold",
    sample_count: score.sample_count,
    denominators: {
      samples: score.sample_count,
      high_risk: high.denominator,
      critical: critical.denominator,
      false_negatives: score.sample_count,
    },
    accuracy: metric(Math.round(score.accuracy * score.sample_count), score.sample_count),
    high_recall: high,
    critical_recall: critical,
    high_critical_recall: highCritical,
    high_risk_recall: cases || options.risk_denominators?.high !== undefined ? high.rate : null,
    false_negative_rate: rate(falseNegativeCount, score.sample_count),
    false_negative_count: falseNegativeCount,
    per_class_metrics: perClassMetrics,
    category_metrics: perClassMetrics,
    evidence_coverage: score.evidence_coverage,
    latency: { p50_ms: score.p50_latency_ms, p95_ms: score.p95_latency_ms },
    cost: { average: score.average_cost, total: totalCost },
    p50_latency_ms: score.p50_latency_ms,
    p95_latency_ms: score.p95_latency_ms,
    average_cost: score.average_cost,
    model_version: modelVersion,
    prompt_version: promptVersion,
    rule_version: ruleVersion,
    dataset_version: datasetVersion,
    versions: { model: modelVersion, prompt: promptVersion, rule: ruleVersion, dataset: datasetVersion },
    failure_case_ids: failureCaseIds,
    failed_case_ids: failureCaseIds,
    failure_reasons: [...score.failure_reasons],
  };
}

export const createEvaluationReport = buildEvaluationReport;
