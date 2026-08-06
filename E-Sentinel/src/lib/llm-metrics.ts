// LLM observability: tracking response times, token usage, costs, and error rates.

import { supabaseAdmin } from "./supabase";

interface LLMCallMetric {
  endpoint: string;
  model: string;
  responseTimeMs: number;
  tokensUsed: number;
  costEstimate: number;
  success: boolean;
  cached: boolean;
  timestamp: number;
}

const metrics: LLMCallMetric[] = [];
const MAX_METRICS = 1000;

// Approximate costs per 1K tokens (input+output average), in CNY
const MODEL_COSTS: Record<string, number> = {
  "moonshot-v1-8k": 0.004,
  "moonshot-v1-32k": 0.008,
  "moonshot-v1-128k": 0.012,
  "gpt-4o-mini": 0.0015,
  "gpt-4o": 0.03,
  "claude-3-haiku": 0.003,
  "claude-3-sonnet": 0.015,
};

export function recordLLMCall(params: {
  endpoint: string;
  model: string;
  responseTimeMs: number;
  tokensUsed?: number;
  success: boolean;
  cached?: boolean;
}): void {
  const costPerK = MODEL_COSTS[params.model] || 0.005;
  const entry: LLMCallMetric = {
    endpoint: params.endpoint,
    model: params.model,
    responseTimeMs: params.responseTimeMs,
    tokensUsed: params.tokensUsed || 0,
    costEstimate: Math.round((params.tokensUsed || 0) / 1000 * costPerK * 10000) / 10000,
    success: params.success,
    cached: params.cached || false,
    timestamp: Date.now(),
  };
  metrics.push(entry);
  if (metrics.length > MAX_METRICS) metrics.shift();

  void persistMetric(entry);
}

async function persistMetric(entry: LLMCallMetric): Promise<void> {
  if (!supabaseAdmin) return;
  try {
    const { error } = await supabaseAdmin.from("llm_call_logs").insert({
      endpoint: entry.endpoint,
      model: entry.model,
      tokens_used: entry.tokensUsed,
      cost_estimate: entry.costEstimate,
      success: entry.success,
      cached: entry.cached,
      response_time_ms: entry.responseTimeMs,
    });
    if (error) console.error(`[LLMMetrics] DB write failed: ${error.message}`);
  } catch (error) {
    console.error(`[LLMMetrics] DB write failed: ${error instanceof Error ? error.message : "unknown error"}`);
  }
}

type LlmMetricsSummary = {
  totalCalls: number;
  successRate: number;
  avgResponseTimeMs: number;
  totalTokens: number;
  totalCost: number;
  cacheHitRate: number;
  byModel: Record<string, { calls: number; avgMs: number; tokens: number; cost: number }>;
  byEndpoint: Record<string, { calls: number; avgMs: number; errorCount: number }>;
  recentErrors: Array<{ endpoint: string; model: string; time: string }>;
};

function summarizeMetrics(window: LLMCallMetric[]): LlmMetricsSummary {
  if (window.length === 0) {
    return {
      totalCalls: 0, successRate: 0, avgResponseTimeMs: 0, totalTokens: 0, totalCost: 0, cacheHitRate: 0,
      byModel: {}, byEndpoint: {}, recentErrors: [],
    };
  }

  const successCount = window.filter((m) => m.success).length;
  const cachedCount = window.filter((m) => m.cached).length;
  const avgMs = Math.round(window.reduce((a, m) => a + m.responseTimeMs, 0) / window.length);
  const totalTokens = window.reduce((a, m) => a + m.tokensUsed, 0);
  const totalCost = Math.round(window.reduce((a, m) => a + m.costEstimate, 0) * 10000) / 10000;

  // By model
  const byModel: Record<string, { calls: number; avgMs: number; tokens: number; cost: number }> = {};
  for (const m of window) {
    if (!byModel[m.model]) byModel[m.model] = { calls: 0, avgMs: 0, tokens: 0, cost: 0 };
    byModel[m.model].calls++;
    byModel[m.model].tokens += m.tokensUsed;
    byModel[m.model].cost = Math.round((byModel[m.model].cost + m.costEstimate) * 10000) / 10000;
  }
  for (const [model, stats] of Object.entries(byModel)) {
    const modelCalls = window.filter((m) => m.model === model);
    stats.avgMs = Math.round(modelCalls.reduce((a, m) => a + m.responseTimeMs, 0) / modelCalls.length);
  }

  // By endpoint
  const byEndpoint: Record<string, { calls: number; avgMs: number; errorCount: number }> = {};
  for (const m of window) {
    if (!byEndpoint[m.endpoint]) byEndpoint[m.endpoint] = { calls: 0, avgMs: 0, errorCount: 0 };
    byEndpoint[m.endpoint].calls++;
    if (!m.success) byEndpoint[m.endpoint].errorCount++;
  }
  for (const [ep, stats] of Object.entries(byEndpoint)) {
    const epCalls = window.filter((m) => m.endpoint === ep);
    stats.avgMs = Math.round(epCalls.reduce((a, m) => a + m.responseTimeMs, 0) / epCalls.length);
  }

  // Recent errors
  const recentErrors = window
    .filter((m) => !m.success)
    .slice(-10)
    .map((m) => ({ endpoint: m.endpoint, model: m.model, time: new Date(m.timestamp).toISOString() }));

  return {
    totalCalls: window.length,
    successRate: successCount / window.length,
    avgResponseTimeMs: avgMs,
    totalTokens,
    totalCost,
    cacheHitRate: cachedCount / window.length,
    byModel,
    byEndpoint,
    recentErrors,
  };
}

/** Prefer persisted metrics; the in-memory ring buffer remains the fallback. */
export async function getLLMMetrics(timeWindowMs: number = 3600000): Promise<LlmMetricsSummary> {
  const cutoff = new Date(Date.now() - timeWindowMs).toISOString();

  if (supabaseAdmin) {
    try {
      const { data, error } = await supabaseAdmin
        .from("llm_call_logs")
        .select("endpoint, model, tokens_used, cost_estimate, success, cached, response_time_ms, created_at")
        .gte("created_at", cutoff)
        .order("created_at", { ascending: true });

      if (!error && data) {
        return summarizeMetrics(data.map((row: Record<string, unknown>) => ({
          endpoint: String(row.endpoint || ""),
          model: String(row.model || "unknown"),
          responseTimeMs: Number(row.response_time_ms || 0),
          tokensUsed: Number(row.tokens_used || 0),
          costEstimate: Number(row.cost_estimate || 0),
          success: row.success !== false,
          cached: row.cached === true,
          timestamp: Date.parse(String(row.created_at || "")) || Date.now(),
        })));
      }
    } catch (error) {
      console.error(`[LLMMetrics] DB read failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  const cutoffMs = Date.now() - timeWindowMs;
  return summarizeMetrics(metrics.filter((metric) => metric.timestamp >= cutoffMs));
}

export function getSlowQueries(thresholdMs: number = 5000, limit: number = 20): LLMCallMetric[] {
  return metrics
    .filter((m) => m.responseTimeMs > thresholdMs)
    .sort((a, b) => b.responseTimeMs - a.responseTimeMs)
    .slice(0, limit);
}
