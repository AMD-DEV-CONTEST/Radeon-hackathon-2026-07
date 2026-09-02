import { NextRequest, NextResponse } from "next/server";
import { getLLMMetrics, getSlowQueries } from "@/lib/llm-metrics";
import { getCacheStats } from "@/lib/llm-provider";

// GET /api/qa/llm-metrics — LLM observability dashboard data
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const windowMs = parseInt(searchParams.get("window_ms") || "3600000"); // default 1 hour
    const slowThreshold = parseInt(searchParams.get("slow_threshold") || "5000");

    const metrics = await getLLMMetrics(Math.min(windowMs, 86400000));
    const slowQueries = getSlowQueries(slowThreshold, 20);
    const cacheStats = getCacheStats();

    return NextResponse.json({
      metrics,
      slow_queries: slowQueries.map((q) => ({
        endpoint: q.endpoint,
        model: q.model,
        response_time_ms: q.responseTimeMs,
        tokens: q.tokensUsed,
        cached: q.cached,
        success: q.success,
        timestamp: new Date(q.timestamp).toISOString(),
      })),
      cache: cacheStats,
      thresholds: {
        alert_error_rate: 0.05,    // Alert when error rate > 5%
        alert_slow_ms: 8000,       // Alert when avg response > 8s
        alert_cost_per_hour: 50,   // Alert when cost > ¥50/hour
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
