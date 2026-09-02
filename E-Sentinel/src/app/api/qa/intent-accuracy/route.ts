import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { getIntentAccuracyHistory, getIntentAccuracyLatest, getMostRecentDate, recordIntentAccuracy } from "@/lib/intent-accuracy";

// GET — accuracy history for dashboard
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const mode = searchParams.get("mode") || "history";

    if (mode === "latest") {
      const latest = await getIntentAccuracyLatest();
      const mostRecent = await getMostRecentDate();
      return NextResponse.json({ latest, most_recent_date: mostRecent });
    }

    if (mode === "by_platform") {
      const days = Math.min(parseInt(searchParams.get("days") || "7"), 30);
      const cutoff = new Date(Date.now() - days * 86400000).toISOString().split("T")[0];
      const { data: rows } = await supabaseAdmin
        .from("intent_accuracy_logs")
        .select("platform_id, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, target_met")
        .gte("period_date", cutoff);

      if (!rows || rows.length === 0) {
        return NextResponse.json({ platforms: [] });
      }

      const platformMap = new Map<string, { total: number; correct: number; incorrect: number }>();
      for (const r of rows) {
        const key = r.platform_id || "__global__";
        const entry = platformMap.get(key) || { total: 0, correct: 0, incorrect: 0 };
        entry.total += Number(r.total_recognitions);
        entry.correct += Number(r.correct_recognitions);
        entry.incorrect += Number(r.incorrect_recognitions);
        platformMap.set(key, entry);
      }

      const platformIds = [...platformMap.keys()].filter((k) => k !== "__global__");
      const platformNames: Record<string, string> = {};
      if (platformIds.length > 0) {
        const { data: platforms } = await supabaseAdmin
          .from("platforms")
          .select("id, name")
          .in("id", platformIds);
        if (platforms) {
          for (const p of platforms) {
            platformNames[p.id] = p.name;
          }
        }
      }

      const platforms = [...platformMap.entries()]
        .map(([key, entry]) => ({
          platform_id: key === "__global__" ? null : key,
          platform_name: key === "__global__" ? "全局" : platformNames[key] || "未知",
          total: entry.total,
          correct: entry.correct,
          incorrect: entry.incorrect,
          accuracy: entry.total > 0 ? entry.correct / entry.total : 0,
        }))
        .sort((a, b) => a.accuracy - b.accuracy);

      return NextResponse.json({ platforms });
    }

    const days = parseInt(searchParams.get("days") || "30");
    const history = await getIntentAccuracyHistory(Math.min(days, 90));
    const latest = await getIntentAccuracyLatest();
    const mostRecent = await getMostRecentDate();

    // Enrich history with platform names
    const platformIds = [...new Set(history.map((r: any) => r.platform_id).filter(Boolean))];
    const platformNames: Record<string, string> = {};
    if (platformIds.length > 0) {
      const { data: platforms } = await supabaseAdmin
        .from("platforms")
        .select("id, name")
        .in("id", platformIds);
      if (platforms) {
        for (const p of platforms) {
          platformNames[p.id] = p.name;
        }
      }
    }

    const enrichedHistory = history.map((r: any) => ({
      ...r,
      platform_name: r.platform_id ? platformNames[r.platform_id] || null : null,
    }));

    return NextResponse.json({ history: enrichedHistory, latest, most_recent_date: mostRecent });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST — record new accuracy snapshot (called by evaluate route)
export async function POST(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const result = await recordIntentAccuracy({
      platform_id: body.platform_id || null,
      total_recognitions: body.total_recognitions || 0,
      correct_recognitions: body.correct_recognitions || 0,
      incorrect_recognitions: body.incorrect_recognitions || 0,
      coverage_rate: body.coverage_rate || null,
      bad_case_ids: body.bad_case_ids || [],
      notes: body.notes || null,
    });

    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
