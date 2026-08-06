/**
 * Reindex all quality_rules with BGE embeddings.
 * Run: npx tsx --env-file=.env.local scripts/reindex-quality-rules.ts
 */
import { supabaseAdmin } from "../src/lib/supabase";
import { getEmbedding, embeddingToPgVector } from "../src/lib/embedding";

async function main() {
  if (!supabaseAdmin) throw new Error("Supabase not configured");

  // Fetch all rules
  const { data: rules, error } = await supabaseAdmin
    .from("quality_rules")
    .select("id, rule_text");
  if (error) throw new Error(error.message);

  console.log(`Found ${rules.length} quality rules to reindex\n`);

  let updated = 0;
  let failed = 0;

  for (const rule of rules) {
    try {
      const { embedding, cached } = await getEmbedding(rule.rule_text);
      if (embedding.length > 0) {
        const vec = embeddingToPgVector(embedding);
        const { error: updateErr } = await supabaseAdmin
          .from("quality_rules")
          .update({ embedding: vec as any })
          .eq("id", rule.id);

        if (updateErr) {
          console.log(`  ❌ #${rule.id}: ${updateErr.message}`);
          failed++;
        } else {
          console.log(`  ✅ #${rule.id}${cached ? " (cached)" : ""}: ${rule.rule_text.slice(0, 50)}...`);
          updated++;
        }
      } else {
        console.log(`  ⚠️ #${rule.id}: empty embedding`);
        failed++;
      }
    } catch (err: any) {
      console.log(`  ❌ #${rule.id}: ${err.message}`);
      failed++;
    }
  }

  console.log(`\n${"=".repeat(50)}`);
  console.log(`Done: ${updated} updated, ${failed} failed`);
}

main().catch((e) => { console.error(e); process.exit(1); });
