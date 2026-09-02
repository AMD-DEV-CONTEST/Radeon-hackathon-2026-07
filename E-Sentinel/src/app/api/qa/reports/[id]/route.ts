import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const { id } = await params;

  const { data, error } = await supabaseAdmin
    .from("quality_reports")
    .select("*")
    .eq("id", id)
    .single();

  if (error || !data) {
    return NextResponse.json({ error: "Report not found" }, { status: 404 });
  }

  return NextResponse.json(data);
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
  }

  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  if (body.status !== "confirmed") {
    return NextResponse.json({ error: "Unsupported report status" }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("quality_reports")
    .update({ status: "confirmed" })
    .eq("id", id)
    .select()
    .single();

  if (error || !data) {
    return NextResponse.json({ error: error?.message || "Report not found" }, { status: error ? 500 : 404 });
  }

  return NextResponse.json(data);
}
