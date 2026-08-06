import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

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

    const updates: Record<string, unknown> = {};
    if (body.status) updates["status"] = body.status;
    if (body.priority) updates["priority"] = body.priority;
    if (body.resolution) updates["resolution"] = body.resolution;
    if (body.impact_estimate) updates["impact_estimate"] = body.impact_estimate;
    if (body.assigned_to !== undefined) updates["assigned_to"] = body.assigned_to;
    if (body.title) updates["title"] = body.title;
    if (body.description) updates["description"] = body.description;

    if (body.status === "resolved") {
      updates["resolved_at"] = new Date().toISOString();
    }

    const { data, error } = await supabaseAdmin
      .from("optimization_tasks")
      .update(updates)
      .eq("id", id)
      .select()
      .single();

    if (error) {
      if (error.code === "PGRST116") return NextResponse.json({ error: "Not found" }, { status: 404 });
      throw error;
    }

    return NextResponse.json({ task: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[OptTasks] PUT error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
