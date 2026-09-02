import { NextResponse } from "next/server";
import { authorizeRequest } from "@/lib/api-auth";
import { supabaseAdmin } from "@/lib/supabase";
import { loadGovernanceContext } from "@/lib/governance/roles";

/**
 * GET /api/qa/diagnosis/[id]
 * Retrieve a diagnosis session with its findings and reviews.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;

  if (!supabaseAdmin) {
    return NextResponse.json({ error: "Database not configured" }, { status: 500 });
  }

  const { id } = await params;

  let tenantId = "default";
  if (auth.user) {
    const ctx = await loadGovernanceContext(auth.user.id);
    tenantId = ctx?.tenantId ?? "default";
  }

  const { data: session, error } = await supabaseAdmin
    .from("diagnosis_sessions")
    .select("*")
    .eq("id", id)
    .eq("tenant_id", tenantId)
    .single();

  if (error || !session) {
    return NextResponse.json({ error: "Diagnosis session not found" }, { status: 404 });
  }

  // Fetch findings with reviews
  const { data: findings } = await supabaseAdmin
    .from("diagnosis_findings")
    .select("*")
    .eq("session_id", id)
    .order("confidence_score", { ascending: false });

  // Fetch reviews for all findings
  const findingIds = (findings ?? []).map((f: Record<string, unknown>) => f.id);
  let reviews: Record<string, unknown>[] = [];
  if (findingIds.length > 0) {
    const { data: reviewData } = await supabaseAdmin
      .from("diagnosis_reviews")
      .select("*")
      .in("finding_id", findingIds);
    reviews = reviewData ?? [];
  }

  // Fetch work items
  const { data: workItems } = await supabaseAdmin
    .from("diagnosis_work_items")
    .select("*")
    .eq("session_id", id);

  // Attach reviews to findings
  const findingsWithReviews = (findings ?? []).map((f: Record<string, unknown>) => ({
    ...f,
    reviews: reviews.filter((r) => r.finding_id === f.id),
  }));

  return NextResponse.json({
    session,
    findings: findingsWithReviews,
    work_items: workItems ?? [],
  });
}
