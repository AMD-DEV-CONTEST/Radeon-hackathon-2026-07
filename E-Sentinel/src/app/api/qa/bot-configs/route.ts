import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeRequest } from "@/lib/api-auth";
import { canWrite, loadGovernanceContext } from "@/lib/governance/roles";

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  try { return JSON.stringify(error); } catch { return "internal_error"; }
}

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  try {
    const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;

    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platformId = searchParams.get("platform_id");
    const configType = searchParams.get("config_type");
    const status = searchParams.get("status") || "active";
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);

    let query = supabaseAdmin
      .from("bot_configs")
      .select("*")
      .order("updated_at", { ascending: false })
      .limit(limit);
    query = query.eq("tenant_id", context?.tenantId || "default");

    if (platformId) query = query.eq("platform_id", platformId);
    if (configType) query = query.eq("config_type", configType);
    if (status) query = query.eq("status", status);

    const { data, error } = await query;
    if (error) throw error;

    return NextResponse.json({ configs: data || [] });
  } catch (error) {
    const message = formatError(error);
    console.error("[BotConfigs] GET error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;

  try {
    const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;
    if (auth.user && (!context || !canWrite(context.role))) {
      return NextResponse.json({ error: "Operator role required" }, { status: 403 });
    }

    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { platform_id, config_type, config_key, config_value, change_summary, updated_by } = body;

    if (!platform_id || !config_type || !config_key || !config_value) {
      return NextResponse.json(
        { error: "platform_id, config_type, config_key, config_value are required" },
        { status: 400 }
      );
    }

    // Archive the current active version
    await supabaseAdmin
      .from("bot_configs")
      .update({ status: "archived" })
      .eq("platform_id", platform_id)
      .eq("config_type", config_type)
      .eq("config_key", config_key)
      .eq("tenant_id", context?.tenantId || "default")
      .eq("status", "active");

    // Get latest version number
    const { data: versions } = await supabaseAdmin
      .from("bot_configs")
      .select("version")
      .eq("platform_id", platform_id)
      .eq("config_type", config_type)
      .eq("config_key", config_key)
      .eq("tenant_id", context?.tenantId || "default")
      .order("version", { ascending: false })
      .limit(1);

    const nextVersion = (versions?.[0]?.version || 0) + 1;

    const { data, error } = await supabaseAdmin
      .from("bot_configs")
      .insert({
        platform_id,
        config_type,
        config_key,
        config_value,
        version: nextVersion,
        status: "active",
        updated_by: updated_by || null,
        change_summary: change_summary || null,
        tenant_id: context?.tenantId || "default",
      })
      .select()
      .single();

    if (error) throw error;

    return NextResponse.json({ config: data }, { status: 201 });
  } catch (error) {
    const message = formatError(error);
    console.error("[BotConfigs] POST error:", message, "| typeof:", typeof error);
    return NextResponse.json({ error: message || "internal_error" }, { status: 500 });
  }
}
