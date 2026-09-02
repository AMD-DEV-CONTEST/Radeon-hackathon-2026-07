/**
 * Reindex knowledge_entries with embeddings.
 *
 * The seed script (scripts/seed-ecommerce-data.ts) upserts entries without
 * an embedding, so the `match_knowledge_entries` RPC returns similarity=0.
 * This script walks all published entries and writes
 * textToEmbedding(`${title} ${content}`) — matching the POST handler in
 * src/app/api/qa/knowledge/route.ts:140 for consistency.
 *
 * NOTE: filtering on `embedding IS NULL` via PostgREST throws "column does
 * not exist" because the pgvector column isn't exposed for nullity filters,
 * so we iterate all published rows and overwrite (idempotent — same input
 * produces the same vector).
 *
 * Run: npx tsx --env-file=.env.local scripts/reindex-knowledge-embeddings.ts
 */
import { supabaseAdmin } from "../src/lib/supabase";
import { textToEmbedding, embeddingToPgVector } from "../src/lib/embedding";

interface KnowledgeRow {
  id: string;
  title: string | null;
  content: string | null;
}

const FIX_SQL = `
-- Run this in Supabase SQL Editor first if reindex reports
-- "Could not find the 'embedding' column":
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON knowledge_entries
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

NOTIFY pgrst, 'reload schema';
`.trim();

async function main() {
  if (!supabaseAdmin) throw new Error("Supabase not configured");

  // Fetch all published entries — overwriting an existing embedding is safe.
  const { data, error } = await supabaseAdmin
    .from("knowledge_entries")
    .select("id, title, content")
    .eq("status", "published");

  if (error) throw new Error(error.message);

  const rows = (data || []) as KnowledgeRow[];
  console.log(`Found ${rows.length} published knowledge entries to reindex\n`);

  let updated = 0;
  let failed = 0;
  let columnMissing = false;

  for (const row of rows) {
    try {
      const text = `${row.title ?? ""} ${row.content ?? ""}`.trim();
      if (!text) {
        console.log(`  ⚠️ #${row.id}: empty title+content, skipping`);
        failed++;
        continue;
      }

      const embedding = textToEmbedding(text);
      if (embedding.length === 0) {
        console.log(`  ⚠️ #${row.id}: empty embedding`);
        failed++;
        continue;
      }

      const vec = embeddingToPgVector(embedding);
      const { error: updateErr } = await supabaseAdmin
        .from("knowledge_entries")
        .update({ embedding: vec as unknown as string })
        .eq("id", row.id);

      if (updateErr) {
        if (/embedding.*column.*not.*exist|Could not find the 'embedding' column/i.test(updateErr.message)) {
          columnMissing = true;
        }
        console.log(`  ❌ #${row.id}: ${updateErr.message}`);
        failed++;
      } else {
        const preview = String(row.title ?? "").slice(0, 40);
        console.log(`  ✅ #${row.id}: ${preview}`);
        updated++;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`  ❌ #${row.id}: ${msg}`);
      failed++;
    }
  }

  console.log(`\n${"=".repeat(50)}`);
  console.log(`Done: ${updated} updated, ${failed} failed`);

  if (columnMissing) {
    console.log("\n⚠️  knowledge_entries.embedding column is MISSING from the live table.");
    console.log("   Run the following SQL in Supabase SQL Editor, then re-run this script:\n");
    console.log(FIX_SQL);
    console.log();
    process.exitCode = 1;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

