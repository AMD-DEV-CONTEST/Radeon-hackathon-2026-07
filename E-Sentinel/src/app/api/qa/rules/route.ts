import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding } from "@/lib/embedding";

export async function GET() {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const { data, error } = await supabaseAdmin
    .from("quality_rules")
    .select("id, category, rule_text, deduction_min, deduction_max, severity, examples")
    .order("id", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data || []);
}

export async function POST(request: Request) {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const body = await request.json().catch(() => null);
  if (!body?.rule_text || !body?.category) {
    return NextResponse.json({ error: "rule_text and category are required" }, { status: 400 });
  }

  const ruleText = body.rule_text.trim();
  const embedding = textToEmbedding(ruleText);

  const { data, error } = await supabaseAdmin
    .from("quality_rules")
    .insert({
      category: body.category,
      rule_text: ruleText,
      deduction_min: body.deduction_min ?? 5,
      deduction_max: body.deduction_max ?? 20,
      severity: body.severity || "major",
      examples: body.examples || null,
      embedding: JSON.stringify(embedding),
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

export async function DELETE(request: Request) {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const url = new URL(request.url);
  const id = url.searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "id query param required" }, { status: 400 });
  }

  const { error } = await supabaseAdmin
    .from("quality_rules")
    .delete()
    .eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ deleted: id });
}
