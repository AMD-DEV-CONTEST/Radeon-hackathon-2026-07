import { supabaseAdmin } from "../src/lib/supabase";
import { getEmbedding, embeddingToPgVector } from "../src/lib/embedding";

async function main() {
  console.log("supabaseAdmin:", supabaseAdmin ? "OK" : "NULL");

  // 1. Direct RPC with dummy vector
  const dummy = "[" + new Array(1536).fill("0.001").join(",") + "]";
  const { data: d1, error: e1 } = await supabaseAdmin!.rpc("match_quality_rules", {
    query_embedding: dummy,
    match_threshold: 0,
    match_count: 5,
  });
  console.log("1. Dummy vector RPC:", { error: e1?.message, count: (d1 as any[])?.length });

  // 2. Get real embedding and try
  const { embedding, error: embErr } = await getEmbedding("客户投诉物流延迟");
  console.log("2. Embedding:", { len: embedding.length, error: embErr });

  if (embedding.length > 0) {
    const vec = embeddingToPgVector(embedding);
    console.log("3. pgVector first 80 chars:", vec.slice(0, 80));

    const { data: d2, error: e2 } = await supabaseAdmin!.rpc("match_quality_rules", {
      query_embedding: vec,
      match_threshold: 0,
      match_count: 5,
    });
    console.log("4. Real embed RPC:", { error: e2?.message, count: (d2 as any[])?.length });
    if (d2) {
      for (const r of (d2 as any[]).slice(0, 3)) {
        console.log(`   [${r.category}] ${r.rule_text?.slice(0, 50)}... sim=${r.similarity?.toFixed(3)}`);
      }
    }
  }

  // 5. Check if trigram fallback works
  const { data: tri, error: triErr } = await supabaseAdmin!
    .from("quality_rules")
    .select("id, category, rule_text")
    .ilike("rule_text", "%客户%")
    .limit(3);
  console.log("5. Trigram ilike:", { error: triErr?.message, count: tri?.length });
}

main().catch((e) => console.error("FATAL:", e));
