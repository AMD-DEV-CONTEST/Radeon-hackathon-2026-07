import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    if (!supabaseAdmin) {
      return NextResponse.json({ error: "Supabase not configured" }, { status: 500 });
    }

    const { searchParams } = new URL(request.url);
    const limit = Math.min(parseInt(searchParams.get("limit") || "30"), 100);
    const platformId = searchParams.get("platform_id");

    let query = supabaseAdmin
      .from("knowledge_entries")
      .select("*")
      .eq("tenant_id", tenantId)
      .eq("status", "draft")
      .order("priority", { ascending: false })
      .order("created_at", { ascending: false })
      .limit(limit);

    if (platformId) query = query.eq("platform_id", platformId);

    const { data, error } = await query;

    if (error) throw error;

    return NextResponse.json({ entries: data || [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Pending] GET error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
