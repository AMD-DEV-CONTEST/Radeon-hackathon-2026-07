import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";

// GET /api/qa/agent-assist — list agents with recent session stats
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const agentId = searchParams.get("agent_id");

    if (agentId) {
      const { data: agent } = await supabaseAdmin
        .from("profiles")
        .select("id, name, role, team_id")
        .eq("id", agentId)
        .single();

      if (!agent) {
        return NextResponse.json({ error: "Agent not found" }, { status: 404 });
      }

      const { data: sessions } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("id, customer_message, bot_reply, satisfaction, created_at")
        .eq("agent_id", agentId)
        .order("created_at", { ascending: false })
        .limit(20);

      const { data: reports } = await supabaseAdmin
        .from("quality_reports")
        .select("id, total_score, risk_level, violations, created_at")
        .eq("agent_id", agentId)
        .order("created_at", { ascending: false })
        .limit(10);

      return NextResponse.json({
        agent,
        recent_sessions: sessions || [],
        recent_reports: reports || [],
      });
    }

    // List all agents with their session counts and avg scores
    const { data: agents } = await supabaseAdmin
      .from("profiles")
      .select("id, name, role, team_id")
      .eq("role", "agent");

    if (!agents || agents.length === 0) {
      return NextResponse.json({ agents: [] });
    }

    // Batch query all agent stats in parallel
    const agentIds = agents.map((a) => a.id);
    const [sessionCounts, latestReports] = await Promise.all([
      // Get session counts for all agents in one query
      (async () => {
        const { data: rows } = await supabaseAdmin
          .from("bot_chat_sessions")
          .select("agent_id")
          .in("agent_id", agentIds);
        const counts: Record<string, number> = {};
        for (const r of (rows || []) as Array<{ agent_id: string }>) {
          counts[r.agent_id] = (counts[r.agent_id] || 0) + 1;
        }
        return counts;
      })(),
      // Get latest report per agent using a single query
      (async () => {
        const { data: reports } = await supabaseAdmin
          .from("quality_reports")
          .select("agent_id, total_score, risk_level, created_at")
          .in("agent_id", agentIds)
          .order("created_at", { ascending: false });
        // Dedupe: keep only the latest per agent
        const latest: Record<string, Record<string, unknown>> = {};
        for (const r of (reports || []) as Array<Record<string, unknown>>) {
          const aid = r.agent_id as string;
          if (!latest[aid]) latest[aid] = r;
        }
        return latest;
      })(),
    ]);

    const results = agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      team_id: agent.team_id,
      session_count: sessionCounts[agent.id as string] || 0,
      latest_score: (latestReports[agent.id as string]?.total_score as number) ?? null,
      latest_risk: (latestReports[agent.id as string]?.risk_level as string) ?? null,
    }));

    return NextResponse.json({ agents: results });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST /api/qa/agent-assist — get real-time recommendations for a conversation
export async function POST(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const conversation = String(body.conversation || "");
    const agentId = body.agent_id || null;
    const customerId = body.customer_id || null;

    if (!conversation || conversation.length < 10) {
      return NextResponse.json({ error: "Conversation too short" }, { status: 400 });
    }

    // Get customer info and history
    let customerInfo: Record<string, unknown> | null = null;
    let customerHistory: Array<Record<string, unknown>> = [];
    if (customerId) {
      const { data: profile } = await supabaseAdmin
        .from("profiles")
        .select("id, name")
        .eq("id", customerId)
        .maybeSingle();
      customerInfo = profile || null;

      const { data: history } = await supabaseAdmin
        .from("bot_chat_sessions")
        .select("customer_message, bot_reply, satisfaction, created_at")
        .eq("customer_id", customerId)
        .order("created_at", { ascending: false })
        .limit(10);
      customerHistory = (history || []) as Array<Record<string, unknown>>;
    }

    // Semantic search for relevant knowledge entries
    const embedding = textToEmbedding(conversation);
    let knowledgeRecommendations: Array<Record<string, unknown>> = [];
    try {
      const { data: kMatches } = await supabaseAdmin.rpc("match_knowledge_entries", {
        query_embedding: JSON.stringify(embedding),
        match_count: 5,
      });
      knowledgeRecommendations = (kMatches || []) as Array<Record<string, unknown>>;
    } catch {
      // Fallback: keyword search
      const keywords = conversation.replace(/[，,。！？!?\s]+/g, " ").split(" ").filter((w: string) => w.length >= 2).slice(0, 5);
      for (const kw of keywords) {
        const { data: kMatches } = await supabaseAdmin
          .from("knowledge_entries")
          .select("id, title, content, status")
          .eq("status", "published")
          .ilike("title", `%${kw}%`)
          .limit(3);
        if (kMatches) {
          for (const m of kMatches as Array<Record<string, unknown>>) {
            if (!knowledgeRecommendations.find((r) => r.id === m.id)) {
              knowledgeRecommendations.push(m);
            }
          }
        }
      }
    }

    // Search for relevant bot configs/scripts
    let scriptRecommendations: Array<Record<string, unknown>> = [];
    try {
      const { data: sMatches } = await supabaseAdmin.rpc("match_quality_rules", {
        query_embedding: JSON.stringify(embedding),
        match_count: 3,
      });
      scriptRecommendations = (sMatches || []) as Array<Record<string, unknown>>;
    } catch {
      const keywords = conversation.replace(/[，,。！？!?\s]+/g, " ").split(" ").filter((w: string) => w.length >= 2).slice(0, 3);
      for (const kw of keywords) {
        const { data: sMatches } = await supabaseAdmin
          .from("bot_configs")
          .select("id, config_key, config_value, status")
          .eq("status", "active")
          .ilike("config_key", `%${kw}%`)
          .limit(3);
        if (sMatches) {
          for (const m of sMatches as Array<Record<string, unknown>>) {
            if (!scriptRecommendations.find((r) => r.id === m.id)) {
              scriptRecommendations.push(m);
            }
          }
        }
      }
    }

    return NextResponse.json({
      agent_id: agentId,
      customer_info: customerInfo,
      customer_history: customerHistory,
      knowledge_recommendations: knowledgeRecommendations.slice(0, 5),
      script_recommendations: scriptRecommendations.slice(0, 3),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
