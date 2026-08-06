import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

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
      .from("prompts")
      .select("*")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    return NextResponse.json({ prompt: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] GET/:id error:", message);
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

    // Fetch current prompt
    const { data: current } = await supabaseAdmin
      .from("prompts")
      .select("*")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .single();

    if (!current) return NextResponse.json({ error: "Not found" }, { status: 404 });

    const updates: Record<string, unknown> = {};
    let systemPromptChanged = false;

    const editableFields = [
      "name",
      "scene",
      "system_prompt",
      "variables",
      "temperature",
      "max_tokens",
      "status",
      "is_active",
    ];

    for (const field of editableFields) {
      if (body[field] !== undefined) {
        const currentVal = (current as Record<string, unknown>)[field];
        const newVal = body[field];

        // Compare JSON-serialized for objects/arrays
        const isEqual =
          typeof newVal === "object"
            ? JSON.stringify(newVal) === JSON.stringify(currentVal)
            : newVal === currentVal;

        if (!isEqual) {
          updates[field] = body[field];
          if (field === "system_prompt") systemPromptChanged = true;
        }
      }
    }

    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ prompt: current });
    }

    // If activating this prompt, deactivate all others in the same scene
    if (updates["is_active"] === true) {
      const sceneToDeactivate = updates["scene"] !== undefined
        ? (updates["scene"] as string)
        : (current.scene as string);

      await supabaseAdmin
        .from("prompts")
        .update({ is_active: false, updated_at: new Date().toISOString() })
        .eq("scene", sceneToDeactivate)
        .neq("id", id)
        .eq("tenant_id", tenantId);

      await logAudit({
        action: "prompt_activate",
        user_id: body.user_id || null,
        user_name: body.user_name || null,
        resource_type: "prompt",
        resource_id: id,
        detail: { scene: sceneToDeactivate, name: current.name },
      });
    }

    // If system_prompt changed, increment version and record history
    if (systemPromptChanged) {
      const newVersion = (current.version || 1) + 1;
      updates["version"] = newVersion;

      // Insert version history row
      await supabaseAdmin.from("prompt_versions").insert({
        prompt_id: id,
        version: newVersion,
        system_prompt: updates.system_prompt || current.system_prompt,
        variables: updates.variables !== undefined ? updates.variables : current.variables,
        temperature: updates.temperature !== undefined ? updates.temperature : current.temperature,
        max_tokens: updates.max_tokens !== undefined ? updates.max_tokens : current.max_tokens,
        tenant_id: tenantId,
      });

      await logAudit({
        action: "prompt_version_new",
        user_id: body.user_id || null,
        user_name: body.user_name || null,
        resource_type: "prompt",
        resource_id: id,
        detail: { version: newVersion },
      });
    }

    updates["updated_at"] = new Date().toISOString();

    const { data, error } = await supabaseAdmin
      .from("prompts")
      .update(updates)
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) throw error;

    await logAudit({
      action: "prompt_update",
      user_id: body.user_id || null,
      user_name: body.user_name || null,
      resource_type: "prompt",
      resource_id: id,
      detail: { changed_fields: Object.keys(updates).filter((k) => k !== "updated_at") },
    });

    return NextResponse.json({ prompt: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] PATCH/:id error:", message);
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

    // Soft delete — set status to archived
    const { data, error } = await supabaseAdmin
      .from("prompts")
      .update({ status: "archived", updated_at: new Date().toISOString() })
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .select()
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    await logAudit({
      action: "prompt_archive",
      resource_type: "prompt",
      resource_id: id,
    });

    return NextResponse.json({ prompt: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Prompts] DELETE/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
