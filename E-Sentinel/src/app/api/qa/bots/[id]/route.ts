import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";
import { getPublicErrorMessage } from "@/lib/api-error";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }
    const { id } = await params;

    const { data, error } = await supabaseAdmin
      .from("bots")
      .select("*, prompts(name), model_configs(name)")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    const bot = {
      ...data,
      prompt_name: (data.prompts as Record<string, unknown> | null)?.name ?? null,
      model_name: (data.model_configs as Record<string, unknown> | null)?.name ?? null,
      prompts: undefined,
      model_configs: undefined,
    };

    return NextResponse.json({ bot });
  } catch (error) {
    const message = getPublicErrorMessage(error);
    console.error("[Bots] GET/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }
    const { id } = await params;

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

    // Build update payload from provided fields only
    const updates: Record<string, unknown> = { updated_at: new Date().toISOString() };
    if (name !== undefined) updates.name = name;
    if (avatar !== undefined) updates.avatar = avatar;
    if (welcome_message !== undefined) updates.welcome_message = welcome_message;
    if (prompt_id !== undefined) updates.prompt_id = prompt_id;
    if (model_config_id !== undefined) updates.model_config_id = model_config_id;
    if (platform !== undefined) updates.platform = platform;
    if (working_hours !== undefined) updates.working_hours = working_hours;
    if (transfer_keywords !== undefined) updates.transfer_keywords = transfer_keywords;
    if (is_active !== undefined) updates.is_active = is_active;

    const { data, error } = await supabaseAdmin
      .from("bots")
      .update(updates)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    await logAudit({
      action: "bot_update",
      user_id: user_id || null,
      user_name: user_name || null,
      resource_type: "bot",
      resource_id: id,
      detail: { updates: Object.keys(updates).filter((k) => k !== "updated_at") },
    });

    return NextResponse.json({ bot: data });
  } catch (error) {
    const message = getPublicErrorMessage(error);
    console.error("[Bots] PATCH/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }
    const { id } = await params;

    const body = await request.json().catch(() => ({}));
    const { user_id, user_name } = body;

    // Soft delete — set is_active to false
    const { data, error } = await supabaseAdmin
      .from("bots")
      .update({ is_active: false, updated_at: new Date().toISOString() })
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    await logAudit({
      action: "bot_delete",
      user_id: user_id || null,
      user_name: user_name || null,
      resource_type: "bot",
      resource_id: id,
      detail: { soft_delete: true },
    });

    return NextResponse.json({ bot: data });
  } catch (error) {
    const message = getPublicErrorMessage(error);
    console.error("[Bots] DELETE/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
