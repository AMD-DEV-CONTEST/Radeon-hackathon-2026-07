import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

// GET /api/qa/effect-compare — pre/post optimization effect comparison
// Compares satisfaction/conversion metrics before and after a config change
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const configId = searchParams.get("config_id");
    const knowledgeId = searchParams.get("knowledge_id");
    const platformId = searchParams.get("platform_id");

    if (!configId && !knowledgeId) {
      // Return available items for selection
      const [configsRes, knowledgeRes] = await Promise.all([
        supabaseAdmin.from("bot_configs").select("id, config_key, effect_metrics, status").eq("status", "active").limit(10),
        supabaseAdmin.from("knowledge_entries").select("id, title, effect_metrics").eq("status", "published").limit(10),
      ]);
      return NextResponse.json({
        available_configs: configsRes.data || [],
        available_knowledge: knowledgeRes.data || [],
        hint: "Provide config_id or knowledge_id to compare pre/post effect",
      });
    }

    if (configId) {
      // Get the config and its platform_id for proper session filtering
      const { data: config } = await supabaseAdmin
        .from("bot_configs")
        .select("id, config_key, effect_metrics, status, platform_id, updated_at, created_at")
        .eq("id", configId)
        .single();

      if (!config) {
        return NextResponse.json({ error: "Config not found" }, { status: 404 });
      }

      const cfg = config as Record<string, unknown>;
      const cfgPlatformId = cfg.platform_id as string | null;

      // Get recent sessions for this config's platform for post-publish comparison
      if (cfg.status === "active") {
        let sessionQuery = supabaseAdmin
          .from("bot_chat_sessions")
          .select("satisfaction, bot_handled, created_at")
          .gte("created_at", cfg.updated_at as string)
          .limit(200);

        if (cfgPlatformId) sessionQuery = sessionQuery.eq("platform_id", cfgPlatformId);

        const { data: recentSessions } = await sessionQuery;

        const goodCount = (recentSessions || []).filter((s: Record<string, unknown>) => s.satisfaction === "good").length;
        const badCount = (recentSessions || []).filter((s: Record<string, unknown>) => s.satisfaction === "bad").length;
        const total = (recentSessions || []).length;

        const postSnapshot = {
          total_sessions: total,
          good_rate: total > 0 ? goodCount / total : 0,
          bad_rate: total > 0 ? badCount / total : 0,
        };

        return NextResponse.json({
          config_key: cfg.config_key,
          pre_publish: cfg.effect_metrics,
          post_publish: postSnapshot,
        });
      }

      return NextResponse.json({
        config_key: cfg.config_key,
        effect_metrics: cfg.effect_metrics,
      });
    }

    // Knowledge entry effect comparison
    if (knowledgeId) {
      const { data: entry } = await supabaseAdmin
        .from("knowledge_entries")
        .select("id, title, hit_count, gap_source_count, last_hit_at, effect_metrics, updated_at")
        .eq("id", knowledgeId)
        .single();

      if (!entry) {
        return NextResponse.json({ error: "Knowledge entry not found" }, { status: 404 });
      }

      // Get knowledge hit rate after publish
      const { data: recentLogs } = await supabaseAdmin
        .from("knowledge_update_logs")
        .select("update_type, created_at")
        .eq("knowledge_id", knowledgeId)
        .order("created_at", { ascending: false })
        .limit(20);

      return NextResponse.json({
        title: (entry as Record<string, unknown>).title,
        hits: (entry as Record<string, unknown>).hit_count,
        gap_sources: (entry as Record<string, unknown>).gap_source_count,
        last_hit: (entry as Record<string, unknown>).last_hit_at,
        effect_metrics: (entry as Record<string, unknown>).effect_metrics,
        update_log: recentLogs,
      });
    }

    return NextResponse.json({ error: "No valid comparison target" }, { status: 400 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
