import { supabaseAdmin } from "@/lib/supabase";
import { apiOk, apiErr } from "@/lib/api-response";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return apiErr("Tenant scope required", "FORBIDDEN", 403);

  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const { data: published, error } = await supabaseAdmin
      .from("knowledge_entries")
      .select("id, title, category, hit_count, updated_at, content, tone, tags, priority, status")
      .eq("tenant_id", tenantId)
      .eq("status", "published");

    if (error) throw error;

    const entries = published || [];
    const totalHits = entries.reduce((sum, e) => sum + (e.hit_count || 0), 0);
    const totalEntries = entries.length;

    const sortedByHits = [...entries].sort((a, b) => (b.hit_count || 0) - (a.hit_count || 0));
    const topEntry = sortedByHits.length > 0
      ? { title: sortedByHits[0].title, hit_count: sortedByHits[0].hit_count || 0 }
      : null;

    const zeroHitEntries = entries.filter((e) => (e.hit_count || 0) === 0);

    const top20 = sortedByHits.slice(0, 20).map((e) => ({
      id: e.id,
      title: e.title,
      category: e.category,
      hit_count: e.hit_count || 0,
      updated_at: e.updated_at,
    }));

    const zeroHits = zeroHitEntries.slice(0, 10).map((e) => ({
      id: e.id,
      title: e.title,
      category: e.category,
      content: e.content,
      tone: e.tone,
      tags: e.tags,
      priority: e.priority,
      status: e.status,
    }));

    return apiOk({
      totalHits,
      totalEntries,
      topEntry,
      zeroHitCount: zeroHitEntries.length,
      top20,
      zeroHits,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge Stats] GET error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}
