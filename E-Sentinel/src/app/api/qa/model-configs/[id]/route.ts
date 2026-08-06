import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";
import { invalidateProviderCache } from "@/lib/llm-provider";

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
      .from("model_configs")
      .select("*")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (error) {
      if (error.code === "PGRST116")
        return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    return NextResponse.json({ config: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ModelConfigs] GET/:id error:", message);
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
      provider,
      model_name,
      api_key,
      api_url,
      temperature,
      max_tokens,
      top_p,
      is_default,
      is_active,
      priority,
    } = body;

    const updates: Record<string, unknown> = {};
    if (name !== undefined) updates.name = name;
    if (provider !== undefined) updates.provider = provider;
    if (model_name !== undefined) updates.model_name = model_name;
    if (api_key !== undefined) updates.api_key = api_key;
    if (api_url !== undefined) updates.api_url = api_url;
    if (temperature !== undefined) updates.temperature = temperature;
    if (max_tokens !== undefined) updates.max_tokens = max_tokens;
    if (top_p !== undefined) updates.top_p = top_p;
    if (is_default !== undefined) updates.is_default = is_default;
    if (is_active !== undefined) updates.is_active = is_active;
    if (priority !== undefined) updates.priority = priority;

    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ error: "No fields to update" }, { status: 400 });
    }

    // If setting is_default to true, unset other defaults first
    if (is_default === true) {
      await supabaseAdmin
        .from("model_configs")
        .update({ is_default: false })
        .eq("is_default", true)
        .neq("id", id)
        .eq("tenant_id", tenantId);
    }

    const { data, error } = await supabaseAdmin
      .from("model_configs")
      .update(updates)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) throw error;

    invalidateProviderCache();

    await logAudit({
      action: "model_config_update",
      resource_type: "model_config",
      resource_id: String(id),
      detail: updates,
    });

    return NextResponse.json({ config: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ModelConfigs] PATCH/:id error:", message);
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

    // Prevent deletion of the only remaining config
    const { count, error: countError } = await supabaseAdmin
      .from("model_configs")
      .select("*", { count: "exact", head: true })
      .eq("tenant_id", tenantId);

    if (countError) throw countError;

    if (count !== null && count <= 1) {
      return NextResponse.json(
        { error: "Cannot delete the only remaining model configuration" },
        { status: 400 }
      );
    }

    const { error } = await supabaseAdmin
      .from("model_configs")
      .delete()
      .eq("id", id)
      .eq("tenant_id", tenantId);

    if (error) throw error;

    invalidateProviderCache();

    await logAudit({
      action: "model_config_delete",
      resource_type: "model_config",
      resource_id: String(id),
    });

    return NextResponse.json({ status: "deleted", id });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ModelConfigs] DELETE/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
