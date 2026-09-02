// ============================================================================
// Hybrid Search API — 对外暴露混合检索
// GET /api/qa/knowledge/search?q=xxx&mode=rrf&limit=10
// ============================================================================

import { NextResponse } from "next/server";
import { hybridSearch } from "@/lib/hybrid-search";
import { authorizeGovernanceRequest } from "@/lib/governance/authorization";

export async function GET(request: Request) {
  const authorization = await authorizeGovernanceRequest(request);
  if (authorization.error) return authorization.error;
  const tenantId = authorization.context?.tenantId;
  if (!tenantId) return NextResponse.json({ error: "Tenant scope required" }, { status: 403 });

  try {
    const { searchParams } = new URL(request.url);
    const q = searchParams.get("q");
    const mode = (searchParams.get("mode") || "rrf") as "rrf" | "weighted" | "vector_only";
    const limit = Math.min(parseInt(searchParams.get("limit") || "10"), 50);
    const threshold = parseFloat(searchParams.get("threshold") || "0");

    if (!q || !q.trim()) {
      return NextResponse.json({ matches: [], method: "none", total: 0 });
    }

    const result = await hybridSearch(q, { mode, limit, threshold, tenantId });

    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal_error";
    console.error("[HybridSearch API] Error:", message);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
