/**
 * Semantic match against quality_rules using pgvector cosine similarity.
 * Falls back to trigram (ilike) when embedding API is unavailable.
 *
 * Matches the actual DB schema from migration-rag-shadow.sql:
 * quality_rules: id (BIGINT), category, rule_text, deduction_min/max, severity, examples, embedding
 */
import { supabaseAdmin } from "@/lib/supabase";
import { getEmbedding, embeddingToPgVector } from "@/lib/embedding";

export interface MatchedRule {
  id: number;
  rule_text: string;
  category: string;
  severity: string;
  deduction_min: number;
  deduction_max: number;
  examples: string | null;
  similarity: number;
}

export interface MatchResult {
  rules: MatchedRule[];
  method: "semantic" | "trigram" | "none";
  error?: string;
}

export async function matchQualityRules(
  text: string,
  options?: { threshold?: number; count?: number },
): Promise<MatchResult> {
  const threshold = options?.threshold ?? 0.7;
  const count = options?.count ?? 5;

  if (!supabaseAdmin) return { rules: [], method: "none", error: "Supabase not configured" };

  // Try semantic match first
  const { embedding, error } = await getEmbedding(text);

  if (embedding.length > 0) {
    const { data, error: dbError } = await supabaseAdmin.rpc("match_quality_rules", {
      query_embedding: embeddingToPgVector(embedding),
      match_count: count,
    });

    if (!dbError && data) {
      const rules = ((data as MatchedRule[]))
        .filter((r) => r.similarity >= threshold)
        .map((r) => ({ ...r, similarity: Math.round(r.similarity * 100) / 100 }));
      if (rules.length > 0) return { rules, method: "semantic" };
    }
    if (dbError) console.warn("[SemanticMatch] RPC failed, falling back:", dbError.message);
  }

  if (error) console.warn("[SemanticMatch] Embedding unavailable:", error);

  // Fallback: trigram via ilike on rule_text
  try {
    const { data: trigramData, error: trigramError } = await supabaseAdmin
      .from("quality_rules")
      .select("id, category, rule_text, deduction_min, deduction_max, severity, examples")
      .ilike("rule_text", `%${text.slice(0, 50)}%`)
      .limit(count);

    if (!trigramError && trigramData) {
      return {
        rules: (trigramData as MatchedRule[]).map((r) => ({ ...r, similarity: 0 })),
        method: "trigram",
      };
    }
  } catch { /* graceful */ }

  // Last resort: return all rules ordered by severity
  try {
    const { data: fallback } = await supabaseAdmin
      .from("quality_rules")
      .select("id, category, rule_text, deduction_min, deduction_max, severity, examples")
      .order("severity")
      .limit(count);

    return {
      rules: ((fallback as MatchedRule[]) || []).map((r) => ({ ...r, similarity: 0 })),
      method: "none",
    };
  } catch {
    return { rules: [], method: "none", error: "All matching methods failed" };
  }
}
