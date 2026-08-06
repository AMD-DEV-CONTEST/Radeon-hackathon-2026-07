import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { apiOk, apiErr } from "@/lib/api-response";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return apiErr("Tenant scope required", "FORBIDDEN", 403);
  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const { searchParams } = new URL(request.url);
    const scene = searchParams.get("scene");
    const status = searchParams.get("status");
    const search = searchParams.get("search");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);

    let query = supabaseAdmin
      .from("prompts")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit)
      .eq("tenant_id", tenantId);

    if (scene && scene !== "all") query = query.eq("scene", scene);
    if (status && status !== "all") query = query.eq("status", status);
    if (search) query = query.ilike("name", `%${search}%`);

    const { data, error } = await query;
    if (error) throw error;

    return apiOk({ prompts: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] GET error:", message);
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
      scene,
      system_prompt,
      variables,
      temperature,
      max_tokens,
      user_id,
      user_name,
    } = body;

    if (!name || !scene) {
      return apiErr("name and scene are required", "BAD_REQUEST", 400);
    }

    // Insert the prompt
    const { data: prompt, error } = await supabaseAdmin
      .from("prompts")
      .insert({
        name,
        scene: scene || "general",
        system_prompt: system_prompt || "",
        variables: variables || null,
        temperature: temperature ?? 0.7,
        max_tokens: max_tokens ?? 2048,
        version: 1,
        status: "draft",
        tenant_id: tenantId,
      })
      .select()
      .single();

    if (error) throw error;

    // Insert initial version record
    await supabaseAdmin.from("prompt_versions").insert({
      prompt_id: prompt.id,
      version: 1,
      system_prompt: prompt.system_prompt,
      variables: prompt.variables,
      temperature: prompt.temperature,
      max_tokens: prompt.max_tokens,
      tenant_id: tenantId,
    });

    await logAudit({
      action: "prompt_create",
      user_id: user_id || null,
      user_name: user_name || null,
      resource_type: "prompt",
      resource_id: prompt.id,
      detail: { name, scene },
    });

    return apiOk({ prompt }, 201);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] POST error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}

export async function PATCH(request: Request) {
  const authorization = await authorizeGovernanceRequest(request, { mutation: true });
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return apiErr("Tenant scope required", "FORBIDDEN", 403);
  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const { searchParams } = new URL(request.url);
    const action = searchParams.get("action");

    if (action !== "activate") {
      return apiErr("Invalid action. Use ?action=activate", "BAD_REQUEST", 400);
    }

    const body = await request.json().catch(() => ({}));
    const { id, user_id, user_name } = body;

    if (!id) {
      return apiErr("id is required", "BAD_REQUEST", 400);
    }

    // Fetch the prompt to get its scene
    const { data: target, error: fetchErr } = await supabaseAdmin
      .from("prompts")
      .select("id, scene, name")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (fetchErr || !target) {
      return apiErr("Prompt not found", "NOT_FOUND", 404);
    }

    // Deactivate all other prompts in the same scene
    await supabaseAdmin
      .from("prompts")
      .update({ is_active: false, updated_at: new Date().toISOString() })
      .eq("scene", target.scene)
      .neq("id", id)
      .eq("tenant_id", tenantId);

    // Activate this prompt
    const { data: activated, error: updateErr } = await supabaseAdmin
      .from("prompts")
      .update({ is_active: true, updated_at: new Date().toISOString() })
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (updateErr) throw updateErr;

    await logAudit({
      action: "prompt_activate",
      user_id: user_id || null,
      user_name: user_name || null,
      resource_type: "prompt",
      resource_id: id,
      detail: { scene: target.scene, name: target.name },
    });

    return apiOk({ prompt: activated });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] PATCH error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}
