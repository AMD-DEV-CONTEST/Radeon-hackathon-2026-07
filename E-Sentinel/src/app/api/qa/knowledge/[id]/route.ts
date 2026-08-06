import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { createCorrelationId } from "@/lib/correlation";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    const { data, error } = await supabaseAdmin
      .from("knowledge_entries")
      .select("*")
      .eq("id", id)
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    return NextResponse.json({ entry: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] GET/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;
    const body = await request.json().catch(() => ({}));

    // Fetch current version
    const { data: current } = await supabaseAdmin
      .from("knowledge_entries")
      .select("*")
      .eq("id", id)
      .single();

    if (!current) return NextResponse.json({ error: "Not found" }, { status: 404 });

    const updates: Record<string, unknown> = {};
    const changedFields: string[] = [];

    const editableFields = ["title", "content", "keywords", "tags", "tone", "category", "priority", "status", "source", "platform_id"];
    for (const field of editableFields) {
      if (body[field] !== undefined && body[field] !== (current as any)[field]) {
        updates[field] = body[field];
        changedFields.push(field);
      }
    }

    if (body.updated_by) updates["updated_by"] = body.updated_by;

    // Normalize array fields — guard against non-array values from client
    if (updates.tags !== undefined && !Array.isArray(updates.tags)) updates.tags = [];
    if (updates.keywords !== undefined && !Array.isArray(updates.keywords)) updates.keywords = [];
    if (updates.priority !== undefined && typeof updates.priority !== "number") updates.priority = Number(updates.priority) || 0;

    if (changedFields.length === 0 && !body.updated_by) {
      return NextResponse.json({ entry: current });
    }

    // Recompute embedding if title or content changed
    const newTitle = (updates.title as string) || current.title;
    const newContent = (updates.content as string) || current.content;
    if (updates.title || updates.content) {
      const embedding = textToEmbedding(`${newTitle} ${newContent}`);
      updates["embedding"] = embeddingToPgVector(embedding);
    }

    updates["version"] = (current.version || 1) + 1;
    updates["updated_at"] = new Date().toISOString();

    const { data, error } = await supabaseAdmin
      .from("knowledge_entries")
      .update(updates)
      .eq("id", id)
      .select()
      .single();

    if (error) throw error;

    // Log each changed field
    const correlationId = createCorrelationId("kn");
    for (const field of changedFields) {
      await supabaseAdmin.from("knowledge_update_logs").insert({
        knowledge_id: id,
        update_type: "update",
        field_changed: field,
        old_value: String((current as any)[field] || ""),
        new_value: String((data as any)[field] || ""),
        updated_by: body.updated_by || null,
        correlation_id: correlationId,
      }).select().maybeSingle();
    }

    return NextResponse.json({ entry: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] PUT/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { id } = await params;

    // Soft delete — archive
    const { data, error } = await supabaseAdmin
      .from("knowledge_entries")
      .update({ status: "archived", updated_at: new Date().toISOString() })
      .eq("id", id)
      .select()
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    await supabaseAdmin.from("knowledge_update_logs").insert({
      knowledge_id: id,
      update_type: "archive",
      correlation_id: createCorrelationId("kn"),
    }).select().maybeSingle();

    return NextResponse.json({ entry: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] DELETE/:id error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
