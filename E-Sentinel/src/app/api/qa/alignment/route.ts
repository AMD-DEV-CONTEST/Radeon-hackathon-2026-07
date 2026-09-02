import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

const RISK_LEVELS = ["low", "medium", "high", "critical"] as const;

function riskBucket(score: number): string {
  if (score >= 90) return "low";
  if (score >= 75) return "medium";
  if (score >= 60) return "high";
  return "critical";
}

// ── Cohen's Kappa ──────────────────────────────────────
function computeKappa(pairs: { ai: string; human: string }[]): {
  kappa: number;
  po: number;
  pe: number;
  n: number;
  matrix: Record<string, Record<string, number>>;
} {
  const n = pairs.length;
  if (n === 0) return { kappa: 0, po: 0, pe: 0, n: 0, matrix: {} };

  // Build confusion matrix
  const matrix: Record<string, Record<string, number>> = {};
  for (const lvl of RISK_LEVELS) {
    matrix[lvl] = {};
    for (const lvl2 of RISK_LEVELS) {
      matrix[lvl][lvl2] = 0;
    }
  }

  for (const { ai, human } of pairs) {
    if (matrix[ai]?.[human] !== undefined) {
      matrix[ai][human]++;
    }
  }

  // Po = observed agreement
  let agreements = 0;
  for (const lvl of RISK_LEVELS) {
    agreements += matrix[lvl][lvl];
  }
  const po = agreements / n;

  // Pe = expected agreement by chance
  let pe = 0;
  for (const lvl of RISK_LEVELS) {
    const rowSum = RISK_LEVELS.reduce((s, l) => s + matrix[lvl][l], 0);
    const colSum = RISK_LEVELS.reduce((s, l) => s + matrix[l][lvl], 0);
    pe += (rowSum / n) * (colSum / n);
  }

  // Handle pe === 1 edge case
  const kappa = pe === 1 ? 1 : (po - pe) / (1 - pe);

  return { kappa, po, pe, n, matrix };
}

export async function GET() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { data: reports, error } = await supabaseAdmin
      .from("quality_reports")
      .select("id, total_score, human_score, risk_level")
      .in("review_mode", ["shadow", "active"])
      .not("human_score", "is", null)
      .order("created_at", { ascending: false })
      .limit(500);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // Separate shadow (for Kappa) and all (for trend)
    const shadowPairs: { ai: string; human: string }[] = [];
    const allPairs: { id: string; ai_score: number; human_score: number; ai_risk: string; human_risk: string; mode: string }[] = [];

    for (const r of reports || []) {
      const humanRisk = riskBucket(r.human_score);
      const pair = {
        id: r.id,
        ai_score: r.total_score,
        human_score: r.human_score,
        ai_risk: r.risk_level,
        human_risk: humanRisk,
        mode: (r as any).review_mode || "active",
      };
      allPairs.push(pair);

      // Kappa calculation uses ALL reports with human_score (not just shadow)
      shadowPairs.push({ ai: r.risk_level, human: humanRisk });
    }

    const kappa = computeKappa(shadowPairs);

    // Agreement breakdown by risk level
    const byLevel: Record<string, { total: number; agreed: number; rate: number }> = {};
    for (const lvl of RISK_LEVELS) {
      const total = shadowPairs.filter(p => p.ai === lvl || p.human === lvl).length;
      const agreed = shadowPairs.filter(p => p.ai === lvl && p.human === lvl).length;
      byLevel[lvl] = {
        total,
        agreed,
        rate: total > 0 ? agreed / shadowPairs.filter(p => p.ai === lvl).length : 0,
      };
    }

    return NextResponse.json({
      kappa: Math.round(kappa.kappa * 1000) / 1000,
      po: Math.round(kappa.po * 1000) / 1000,
      pe: Math.round(kappa.pe * 1000) / 1000,
      sample_count: kappa.n,
      interpretation:
        kappa.kappa < 0 ? "低于随机水平，AI 判分需要根本性调整" :
        kappa.kappa < 0.4 ? "一致性差，建议继续影子模式观察" :
        kappa.kappa < 0.6 ? "中度一致，可小范围开启告警" :
        kappa.kappa < 0.8 ? "高度一致，可以正式上线" :
        kappa.kappa < 0.9 ? "很高一致，上线信心充足" :
        "几乎完全一致",
      ready_for_production: kappa.kappa >= 0.9,
      by_level: byLevel,
      confusion_matrix: kappa.matrix,
      comparisons: allPairs.slice(0, 20), // latest 20 for detail view
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
