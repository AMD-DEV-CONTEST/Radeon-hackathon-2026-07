import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { logAudit } from "@/lib/audit";

export async function GET() {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { data, error } = await supabaseAdmin
      .from("compliance_rules")
      .select("*")
      .order("risk_level", { ascending: true })
      .order("category");

    if (error) throw error;

    return NextResponse.json({ rules: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const { rule_text, pattern, risk_level, category, action_type, description, exemption_tags } = body;

    if (!rule_text || !pattern || !risk_level || !category) {
      return NextResponse.json({ error: "rule_text, pattern, risk_level, and category are required" }, { status: 400 });
    }

    if (![1, 2, 3, 4].includes(risk_level)) {
      return NextResponse.json({ error: "risk_level must be 1-4" }, { status: 400 });
    }

    const validCategories = ["advertising_law", "absolute_claim", "false_promise", "platform_rule", "competitor_mention", "tone_violation", "sensitive_word"];
    if (!validCategories.includes(category)) {
      return NextResponse.json({ error: `Invalid category. Must be one of: ${validCategories.join(", ")}` }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("compliance_rules")
      .insert({
        rule_text,
        pattern,
        risk_level,
        category,
        action_type: action_type || "block",
        description: description || null,
        exemption_tags: exemption_tags || [],
      })
      .select()
      .single();

    if (error) throw error;

    await logAudit({
      action: "compliance_warn",
      resource_type: "compliance_rules",
      resource_id: data.id,
      detail: { rule_text, risk_level, category },
    });

    return NextResponse.json({ rule: data }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json({ error: "id parameter is required" }, { status: 400 });
    }

    // Soft-delete: deactivate instead of removing
    const { error } = await supabaseAdmin
      .from("compliance_rules")
      .update({ is_active: false, updated_at: new Date().toISOString() })
      .eq("id", id);

    if (error) throw error;

    await logAudit({
      action: "compliance_warn",
      resource_type: "compliance_rules",
      resource_id: id,
      detail: { action: "deactivated" },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PATCH(request: NextRequest) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json();
    const { id, is_active } = body;

    if (!id || typeof is_active !== "boolean") {
      return NextResponse.json({ error: "id and is_active (boolean) are required" }, { status: 400 });
    }

    const { error } = await supabaseAdmin
      .from("compliance_rules")
      .update({ is_active, updated_at: new Date().toISOString() })
      .eq("id", id);

    if (error) throw error;

    await logAudit({
      action: "compliance_warn",
      resource_type: "compliance_rules",
      resource_id: id,
      detail: { action: is_active ? "activated" : "deactivated" },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
