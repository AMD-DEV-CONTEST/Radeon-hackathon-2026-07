// ============================================================================
// GET /api/qa/quality-dashboard — quality monitoring data endpoint.
// Powers the QualityMonitorPanel with per-intent scores, throttle decisions,
// alert status, and trend data.
// ============================================================================

import { NextResponse } from "next/server";
import { getGlobalQualitySnapshot } from "@/lib/monitoring/quality-metrics";
import { decideGlobalThrottle, decideIntentThrottle } from "@/lib/monitoring/auto-throttle";
import { evaluateAlerts, dispatchAlerts } from "@/lib/monitoring/alert-engine";
import { getConfigNumber, getConfigString } from "@/lib/system-config";
import type { ThrottleDecision } from "@/lib/monitoring/auto-throttle";
import { authorizeRequest } from "@/lib/api-auth";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const action = url.searchParams.get("action") || "snapshot";
  const windowHours = parseInt(url.searchParams.get("hours") || "24", 10);
  const auth = await authorizeRequest(request, { mutation: action === "override" });
  if (auth.error) return auth.error;

  try {
    // ── Main snapshot endpoint ──
    if (action === "snapshot") {
      const snapshot = await getGlobalQualitySnapshot(Math.min(windowHours, 168));

      // Get current traffic ratio from config
      const currentRatio = await getConfigNumber("tmall_reply_ratio", 0.1);

      // Throttle decision
      const throttle = decideGlobalThrottle(snapshot, currentRatio);

      // Per-intent throttle decisions
      const intentThrottles: Record<string, ThrottleDecision> = {};
      for (const intent of snapshot.intents) {
        intentThrottles[intent.intent] = decideIntentThrottle(intent, currentRatio);
      }

      // Auto-throttle config
      const autoThrottleEnabled = (await getConfigString("tmall_auto_throttle_enabled", "false")) === "true";

      return NextResponse.json({
        snapshot,
        throttle,
        intentThrottles,
        autoThrottleEnabled,
        currentRatio,
        windowHours,
        generatedAt: new Date().toISOString(),
      });
    }

    // ── Alerts endpoint ──
    if (action === "alerts") {
      const snapshot = await getGlobalQualitySnapshot(Math.min(windowHours, 168));
      const alerts = evaluateAlerts(snapshot);

      // Auto-dispatch if enabled
      const autoDispatchEnabled = (await getConfigString("tmall_alert_auto_dispatch", "false")) === "true";
      if (autoDispatchEnabled && alerts.length > 0) {
        dispatchAlerts(alerts).catch(() => {});
      }

      return NextResponse.json({ alerts, snapshot: { overallQuality: snapshot.overallQuality, overallRisk: snapshot.overallRisk, totalReplies24h: snapshot.totalReplies24h } });
    }

    // ── Throttle override (POST only, but accept via GET with action=override for simplicity) ──
    if (action === "override") {
      const ratioParam = url.searchParams.get("ratio");
      if (ratioParam !== null) {
        const ratio = parseFloat(ratioParam);
        if (isNaN(ratio) || ratio < 0 || ratio > 1) {
          return NextResponse.json({ error: "ratio must be 0-1" }, { status: 400 });
        }

        const { setConfigString } = await import("@/lib/system-config");
        await setConfigString("tmall_reply_ratio", String(ratio));
        return NextResponse.json({ status: "ok", ratio });
      }
      return NextResponse.json({ error: "?ratio= required" }, { status: 400 });
    }

    return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "internal_error";
    console.error("[QualityDashboard] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
