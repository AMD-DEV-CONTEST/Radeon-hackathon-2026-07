import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { apiOk, apiErr } from "@/lib/api-response";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";
import { invalidateProviderCache } from "@/lib/llm-provider";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return apiErr("Tenant scope required", "FORBIDDEN", 403);
  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const { data, error } = await supabaseAdmin
      .from("model_configs")
      .select("*")
      .order("priority", { ascending: true })
      .eq("tenant_id", tenantId);

    if (error) throw error;

    return apiOk({ configs: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ModelConfigs] GET error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}

export async function POST(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return apiErr("Tenant scope required", "FORBIDDEN", 403);
  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const body = await request.json().catch(() => ({}));
    const {
      name,
      provider,
      model_name,
      temperature,
      max_tokens,
      top_p,
      is_default,
      priority,
    } = body;

    if (!name || !provider || !model_name) {
      return apiErr("name, provider, and model_name are required", "BAD_REQUEST", 400);
    }

    // If is_default is true, unset other defaults first
    if (is_default) {
      await supabaseAdmin
        .from("model_configs")
        .update({ is_default: false })
        .eq("is_default", true)
        .eq("tenant_id", tenantId);
    }

    const { data, error } = await supabaseAdmin
      .from("model_configs")
      .insert({
        name,
        provider,
        model_name,
        temperature: temperature ?? 0.7,
        max_tokens: max_tokens ?? 4096,
        top_p: top_p ?? null,
        is_default: is_default ?? false,
        is_active: true,
        priority: priority ?? 99,
        tenant_id: tenantId,
      })
      .select()
      .single();

    if (error) throw error;

    invalidateProviderCache();

    await logAudit({
      action: "model_config_create",
      resource_type: "model_config",
      resource_id: String(data.id),
      detail: { name, provider, model_name },
    });

    return apiOk({ config: data }, 201);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[ModelConfigs] POST error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}
