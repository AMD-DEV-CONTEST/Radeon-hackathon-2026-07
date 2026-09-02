import { supabaseAdmin } from "@/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "@/lib/embedding";
import { createCorrelationId } from "@/lib/correlation";
import { apiOk, apiErr } from "@/lib/api-response";
import { authorizeRequest } from "@/lib/api-auth";
import { logAudit } from "@/lib/audit";
import { canWrite, loadGovernanceContext } from "@/lib/governance/roles";

/** Ensure all fields from the database have safe defaults — guards against NULL
 *  values from ALTER TABLE additions (tags, tone, hit_count, effect_metrics, etc.) */
function normalizeEntry(raw: Record<string, unknown>): Record<string, unknown> {
  return {
    ...raw,
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    keywords: Array.isArray(raw.keywords) ? raw.keywords : [],
    tone: raw.tone || null,
    hit_count: typeof raw.hit_count === "number" ? raw.hit_count : 0,
    version: typeof raw.version === "number" ? raw.version : 1,
    priority: typeof raw.priority === "number" ? raw.priority : 0,
    status: raw.status || "draft",
    category: raw.category || "faq",
    title: String(raw.title || ""),
    content: String(raw.content || ""),
    effect_metrics:
      raw.effect_metrics && typeof raw.effect_metrics === "object"
        ? raw.effect_metrics
        : null,
    last_hit_at: raw.last_hit_at || null,
    source: raw.source || null,
  };
}

export async function GET(request: Request) {
  const auth = await authorizeRequest(request);
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;

  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const { searchParams } = new URL(request.url);
    const category = searchParams.get("category");
    const platformId = searchParams.get("platform_id");
    const status = searchParams.get("status") || "published";
    const query = searchParams.get("q");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50"), 100);
    const tone = searchParams.get("tone");
    const tagsFilter = searchParams.get("tags");
    const sort = searchParams.get("sort") || "newest";

    let dbQuery = supabaseAdmin
      .from("knowledge_entries")
      .select("*")
      .limit(limit);

    if (category) dbQuery = dbQuery.eq("category", category);
    if (platformId) dbQuery = dbQuery.eq("platform_id", platformId);
    dbQuery = dbQuery.eq("tenant_id", context?.tenantId || "default");
    if (status !== "all") dbQuery = dbQuery.eq("status", status);
    if (tone && tone !== "all") dbQuery = dbQuery.eq("tone", tone);

    // Sort ordering
    if (sort === "popular") {
      dbQuery = dbQuery.order("hit_count", { ascending: false });
    } else if (sort === "name") {
      dbQuery = dbQuery.order("title", { ascending: true });
    } else {
      // default: newest
      dbQuery = dbQuery.order("priority", { ascending: false })
        .order("updated_at", { ascending: false });
    }

    const { data, error } = await dbQuery;

    if (error) throw error;

    let entries = (data || []).map(normalizeEntry);

    // Full-text search via keyword match (server-side filter for RAG results)
    if (query && query.trim()) {
      const q = query.trim().toLowerCase();
      entries = entries.filter(
        (e: Record<string, unknown>) => {
          const title = String(e.title || "").toLowerCase();
          const content = String(e.content || "").toLowerCase();
          const keywords: string[] = Array.isArray(e.keywords) ? e.keywords : [];
          return title.includes(q) ||
            content.includes(q) ||
            keywords.some((k: string) => String(k || "").toLowerCase().includes(q));
        }
      );
    }

    // Filter by tags (comma-separated, matches entries with ANY of the given tags)
    if (tagsFilter && tagsFilter.trim()) {
      const filterTags = tagsFilter.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
      if (filterTags.length > 0) {
        entries = entries.filter(
          (e: Record<string, unknown>) => {
            const entryTags: string[] = Array.isArray(e.tags) ? e.tags : [];
            return filterTags.some((ft) =>
              entryTags.some((et) => String(et || "").toLowerCase().includes(ft))
            );
          }
        );
      }
    }

    return apiOk({ entries });
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] GET error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}

export async function POST(request: Request) {
  const auth = await authorizeRequest(request, { mutation: true });
  if (auth.error) return auth.error;
  const context = auth.user ? await loadGovernanceContext(auth.user.id) : null;
  if (auth.user && (!context || !canWrite(context.role))) {
    return apiErr("Operator role required", "FORBIDDEN", 403);
  }

  try {
    if (!supabaseAdmin) {
      return apiErr("Supabase not configured", "CONFIG_ERROR", 500);
    }

    const body = await request.json().catch(() => ({}));
    const {
      category,
      platform_id,
      title,
      content,
      keywords,
      tags,
      tone,
      priority,
      source,
      updated_by,
    } = body;

    if (!category || !title || !content) {
      return apiErr("category, title, and content are required", "BAD_REQUEST", 400);
    }

    const validCategories = ["product", "faq", "after_sales_policy", "campaign", "greeting"];
    if (!validCategories.includes(category)) {
      return apiErr(`Invalid category. Must be one of: ${validCategories.join(", ")}`, "BAD_REQUEST", 400);
    }

    const embedding = textToEmbedding(`${title} ${content}`);
    const correlationId = createCorrelationId("kn");

    const { data, error } = await supabaseAdmin
      .from("knowledge_entries")
      .insert({
        category,
        platform_id: platform_id || null,
        title,
        content,
        keywords: Array.isArray(keywords) ? keywords : [],
        tags: Array.isArray(tags) ? tags : [],
        tone: tone || null,
        priority: typeof priority === "number" ? priority : 0,
        source: source || null,
        status: "published",
        embedding: embeddingToPgVector(embedding),
        updated_by: updated_by || null,
        version: 1,
        tenant_id: context?.tenantId || "default",
      })
      .select()
      .single();

    if (error) throw error;

    // Log the creation
    await supabaseAdmin.from("knowledge_update_logs").insert({
      knowledge_id: data.id,
      update_type: "create",
      updated_by: updated_by || null,
      correlation_id: correlationId,
    }).select().maybeSingle();

    await logAudit({
      action: "knowledge_create",
      user_id: auth.user?.id || null,
      resource_type: "knowledge_entry",
      resource_id: data.id,
      detail: { category, source: source || null },
      correlation_id: correlationId,
    });

    return apiOk({ entry: data }, 201);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[Knowledge] POST error:", message);
    return apiErr(message, "INTERNAL_ERROR", 500);
  }
}
