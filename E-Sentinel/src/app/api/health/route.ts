import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

type CheckStatus = "ok" | "unavailable";

interface ReadinessCheck {
  status: CheckStatus;
  detail?: string;
}

async function checkSupabase(): Promise<ReadinessCheck> {
  if (!supabaseAdmin) return { status: "unavailable", detail: "not_configured" };

  try {
    const { error } = await supabaseAdmin.from("system_configs").select("config_key").limit(1);
    return error ? { status: "unavailable", detail: error.message } : { status: "ok" };
  } catch (error) {
    return { status: "unavailable", detail: error instanceof Error ? error.message : "query_failed" };
  }
}

async function checkPgVector(): Promise<ReadinessCheck> {
  if (!supabaseAdmin) return { status: "unavailable", detail: "supabase_unavailable" };

  try {
    const { error } = await supabaseAdmin.from("knowledge_entries").select("embedding").limit(1);
    return error ? { status: "unavailable", detail: error.message } : { status: "ok" };
  } catch (error) {
    return { status: "unavailable", detail: error instanceof Error ? error.message : "rpc_failed" };
  }
}

function checkLlmProvider(): ReadinessCheck {
  const configured = Boolean(
    process.env.DEEPSEEK_API_KEY ||
    process.env.MOONSHOT_API_KEY ||
    process.env.OPENAI_API_KEY,
  );
  return configured
    ? { status: "ok" }
    : { status: "unavailable", detail: "no_provider_key" };
}

export async function GET(request: Request) {
  const readiness = new URL(request.url).searchParams.get("readiness") === "true";
  if (!readiness) {
    return NextResponse.json({ status: "ok" });
  }

  const [supabase, pgvector] = await Promise.all([checkSupabase(), checkPgVector()]);
  const checks = { supabase, pgvector, llmProvider: checkLlmProvider() };
  const status = Object.values(checks).every((check) => check.status === "ok") ? "ok" : "degraded";

  return NextResponse.json({ status, checks });
}
