import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status");
    const priority = searchParams.get("priority");
    const source = searchParams.get("source");
    const platformId = searchParams.get("platform_id");
    const assignedTo = searchParams.get("assigned_to");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const offset = parseInt(searchParams.get("offset") || "0");

    let query = supabaseAdmin
      .from("optimization_tasks")
      .select("*")
      .order("created_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (status) query = query.eq("status", status);
    if (priority) query = query.eq("priority", priority);
    if (source) query = query.eq("source", source);
    if (platformId) query = query.eq("platform_id", platformId);
    if (assignedTo) query = query.eq("assigned_to", assignedTo);

    const { data, error } = await query;
    if (error) throw error;

    return NextResponse.json({ tasks: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[OptTasks] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const body = await request.json().catch(() => ({}));
    const { source, category, title, description, priority, platform_id, related_chat_id, related_knowledge_id, assigned_to, created_by } = body;

    if (!source || !title || !description) {
      return NextResponse.json({ error: "source, title, and description are required" }, { status: 400 });
    }

    const { data, error } = await supabaseAdmin
      .from("optimization_tasks")
      .insert({
        source, category: category || "general", title, description,
        priority: priority || "medium",
        platform_id: platform_id || null,
        related_chat_id: related_chat_id || null,
        related_knowledge_id: related_knowledge_id || null,
        assigned_to: assigned_to || null,
        created_by: created_by || null,
      })
      .select()
      .single();

    if (error) throw error;

    return NextResponse.json({ task: data }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[OptTasks] POST error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
