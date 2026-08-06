import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";
import { getPublicErrorMessage } from "@/lib/api-error";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const platform = searchParams.get("platform");
    const isActive = searchParams.get("is_active");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);

    let query = supabaseAdmin
      .from("bots")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit)
      .eq("tenant_id", tenantId);

    if (platform) query = query.eq("platform", platform);
    if (isActive === "true" || isActive === "false") query = query.eq("is_active", isActive === "true");

    const { data, error } = await query;

    if (error) throw error;

    // Resolve prompt and model names with separate queries (avoids join issues)
    const bots = await Promise.all((data || []).map(async (row: Record<string, unknown>) => {
      let promptName: string | null = null;
      let modelName: string | null = null;
      if (row.prompt_id && supabaseAdmin) {
        const { data: p } = await supabaseAdmin.from("prompts").select("name").eq("id", row.prompt_id).eq("tenant_id", tenantId).maybeSingle();
        promptName = (p as Record<string, unknown> | null)?.name as string || null;
      }
      if (row.model_config_id && supabaseAdmin) {
        const { data: m } = await supabaseAdmin.from("model_configs").select("name").eq("id", row.model_config_id).eq("tenant_id", tenantId).maybeSingle();
        modelName = (m as Record<string, unknown> | null)?.name as string || null;
      }
      return { ...row, prompt_name: promptName, model_name: modelName };
    }));

    return NextResponse.json({ bots });
  } catch (error) {
    const message = getPublicErrorMessage(error);
    console.error("[Bots] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const {
      name,
      avatar,
      welcome_message,
      prompt_id,
      model_config_id,
      platform,
      working_hours,
      transfer_keywords,
      is_active,
      user_id,
      user_name,
    } = body;

    if (!name) {
      return NextResponse.json({ error: "name is required" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("bots")
      .insert({
        name,
        avatar: avatar || null,
        welcome_message: welcome_message || "您好，我是AI客服助手，请问有什么可以帮您？",
        prompt_id: prompt_id || null,
        model_config_id: model_config_id || null,
        platform: platform || "feishu",
        working_hours: working_hours || { start: "09:00", end: "22:00", timezone: "Asia/Shanghai" },
        transfer_keywords: transfer_keywords || ["转人工"],
        is_active: is_active ?? true,
        tenant_id: tenantId,
      })
      .select()
      .single();

    if (error) throw error;

    await logAudit({
      action: "bot_create",
      user_id: user_id || null,
      user_name: user_name || null,
      resource_type: "bot",
      resource_id: data.id,
      detail: { name, platform },
    });

    return NextResponse.json({ bot: data }, { status: 201 });
  } catch (error) {
    const message = getPublicErrorMessage(error);
    console.error("[Bots] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
