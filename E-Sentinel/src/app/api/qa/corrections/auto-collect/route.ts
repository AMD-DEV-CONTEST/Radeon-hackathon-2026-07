import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(16);
}

export async function POST() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json(
        { error: "Supabase not configured" },
        { status: 500 }
      );
    }

    const yesterday = new Date(Date.now() - 86400000).toISOString();

    // Fetch low-score quality reports from the last 24 hours
    const { data: reports, error: queryErr } = await supabaseAdmin
      .from("quality_reports")
      .select("id, ticket_id, conversation, total_score, risk_level, violations")
      .or("risk_level.eq.critical,total_score.lt.40")
      .gte("created_at", yesterday)
      .order("created_at", { ascending: false });

    if (queryErr) {
      console.error("[AutoCollect] Query error:", queryErr.message);
      return NextResponse.json(
        { error: "Failed to query quality reports" },
        { status: 500 }
      );
    }

    if (!reports || reports.length === 0) {
      return NextResponse.json({ collected: 0, skipped: 0 });
    }

    let collected = 0;
    let skipped = 0;

    for (const report of reports as Array<Record<string, unknown>>) {
      const conversation = String(report.conversation || "");
      const ticketId = String(report.ticket_id || "");
      const totalScore = Number(report.total_score ?? 0);
      const riskLevel = String(report.risk_level || "low");
      const violations = Array.isArray(report.violations) ? report.violations : [];

      if (!conversation || conversation.length < 20) {
        skipped++;
        continue;
      }

      try {
        const contentHash = simpleHash(conversation);
        const { data: existing } = await supabaseAdmin
          .from("correction_samples")
          .select("id")
          .eq("conversation_hash", contentHash)
          .maybeSingle();

        if (existing) {
          skipped++;
          continue;
        }

        await supabaseAdmin.from("correction_samples").insert({
          session_id: ticketId,
          conversation: conversation.substring(0, 2000),
          conversation_hash: contentHash,
          ai_prediction: {
            type: "negative_sample",
            quality_score: totalScore,
            risk_level: riskLevel,
            violations: violations
              .map(
                (v: { rule?: string; category?: string }) =>
                  v.rule || v.category || ""
              )
              .join("; "),
            meta: {
              ticket_id: ticketId,
              auto_collected: true,
              report_id: report.id,
            },
          },
          human_correction: { corrected_text: "" },
          correction_type: "other",
        });

        collected++;
        console.log(
          `[AutoCollect] Collected negative sample: ${ticketId} (score=${totalScore}, risk=${riskLevel})`
        );
      } catch (innerErr) {
        // Graceful: table may not exist
        console.warn(
          "[AutoCollect] Skipping report (table may not exist):",
          innerErr instanceof Error ? innerErr.message : innerErr
        );
        skipped++;
      }
    }

    return NextResponse.json({ collected, skipped });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[AutoCollect] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
