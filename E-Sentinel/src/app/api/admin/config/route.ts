import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";
import { invalidateConfigCache } from "@/lib/system-config";

// GET /api/admin/config — list all system configs
export async function GET(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const category = searchParams.get("category");

    let query = supabaseAdmin
      .from("system_configs")
      .select("*")
      .order("category")
      .order("config_key");

    if (category) {
      query = query.eq("category", category);
    }

    const { data, error } = await query;

    if (error) throw error;

    // Parse typed values for convenience
    const configs = (data || []).map((row: Record<string, unknown>) => ({
      ...row,
      parsed_value: parseConfigValue(String(row.config_value || ""), String(row.value_type || "string")),
    }));

    return NextResponse.json({ configs });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// PUT /api/admin/config — update a config value
export async function PUT(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const { config_key, config_value, updated_by } = body;

    if (!config_key || config_value === undefined) {
      return NextResponse.json({ error: "config_key and config_value are required" }, { status: 400 });
    }

    // Validate value_type consistency
    const { data: existing } = await supabaseAdmin
      .from("system_configs")
      .select("value_type, config_value")
      .eq("config_key", config_key)
      .single();

    if (!existing) {
      return NextResponse.json({ error: "Config key not found" }, { status: 404 });
    }

    const oldValue = existing.config_value;

    const { data, error } = await supabaseAdmin
      .from("system_configs")
      .update({
        config_value: String(config_value),
        updated_by: updated_by || null,
        updated_at: new Date().toISOString(),
      })
      .eq("config_key", config_key)
      .select()
      .single();

    if (error) throw error;

    // Invalidate in-memory config cache so next reads get new value
    invalidateConfigCache();

    await logAudit({
      action: "compliance_warn", // repurposing as general config audit
      resource_type: "system_configs",
      resource_id: data.id,
      detail: {
        config_key,
        old_value: oldValue,
        new_value: String(config_value),
      },
    });

    return NextResponse.json({
      config: {
        ...data,
        parsed_value: parseConfigValue(String(data.config_value), String(data.value_type)),
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function parseConfigValue(value: string, valueType: string): string | number | boolean | unknown {
  switch (valueType) {
    case "number":
      return Number(value);
    case "boolean":
      return value === "true";
    case "json":
      try { return JSON.parse(value); } catch { return value; }
    default:
      return value;
  }
}
