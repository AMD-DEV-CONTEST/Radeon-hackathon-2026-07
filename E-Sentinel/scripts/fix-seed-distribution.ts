// Update existing quality_reports to have a realistic distribution
// of risk levels, statuses, and scores
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_ROLE_KEY || ""
);

async function main() {
  console.log("Fetching all quality_reports...");
  const { data: all, error } = await supabase
    .from("quality_reports")
    .select("id, created_at, risk_level, status, total_score, violations")
    .order("created_at", { ascending: false });

  if (error) { console.error("Fetch error:", error); return; }
  if (!all || all.length === 0) { console.log("No reports found"); return; }

  console.log(`Found ${all.length} reports`);

  // Sort by recency
  const sorted = [...all].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  let updated = 0;

  for (let i = 0; i < sorted.length; i++) {
    const r = sorted[i];
    let newRisk = r.risk_level;
    let newStatus = r.status;
    let newScore = r.total_score;

    // First 10: varied statuses and scores
    if (i < 10) {
      // Valid statuses: pending_review, confirmed, overturned, archived
      if (i === 0 || i === 1) { newRisk = "critical"; newScore = 35 + Math.floor(Math.random() * 20); newStatus = "pending_review"; }
      else if (i === 2 || i === 3) { newRisk = "high"; newScore = 50 + Math.floor(Math.random() * 20); newStatus = "pending_review"; }
      else if (i === 4) { newRisk = "high"; newScore = 55 + Math.floor(Math.random() * 15); newStatus = "confirmed"; }
      else if (i < 8) { newRisk = "medium"; newScore = 65 + Math.floor(Math.random() * 20); newStatus = i === 7 ? "confirmed" : "pending_review"; }
      else { newRisk = "low"; newScore = 85 + Math.floor(Math.random() * 15); newStatus = "confirmed"; }
    }
    // Next 40: mixed distribution
    else if (i < 50) {
      const rand = Math.random();
      if (rand < 0.05) { newRisk = "critical"; newScore = 30 + Math.floor(Math.random() * 25); }
      else if (rand < 0.20) { newRisk = "high"; newScore = 50 + Math.floor(Math.random() * 25); }
      else if (rand < 0.50) { newRisk = "medium"; newScore = 65 + Math.floor(Math.random() * 25); }
      else { newRisk = "low"; newScore = 85 + Math.floor(Math.random() * 15); }

      if (Math.random() < 0.3) newStatus = "confirmed";
      else if (Math.random() < 0.05) newStatus = "archived";
      else newStatus = "pending_review";
    }
    // Rest: mostly low/medium, mostly confirmed
    else {
      const rand = Math.random();
      if (rand < 0.02) { newRisk = "critical"; newScore = 25 + Math.floor(Math.random() * 20); }
      else if (rand < 0.08) { newRisk = "high"; newScore = 55 + Math.floor(Math.random() * 20); }
      else if (rand < 0.30) { newRisk = "medium"; newScore = 70 + Math.floor(Math.random() * 20); }
      else { newRisk = "low"; newScore = 88 + Math.floor(Math.random() * 12); }

      if (Math.random() < 0.6) newStatus = "confirmed";
      else if (Math.random() < 0.1) newStatus = "archived";
      else newStatus = "pending_review";
    }

    // Only update if changed
    if (newRisk !== r.risk_level || newStatus !== r.status || newScore !== r.total_score) {
      const { error: updateErr } = await supabase
        .from("quality_reports")
        .update({ risk_level: newRisk, status: newStatus, total_score: newScore })
        .eq("id", r.id);

      if (updateErr) {
        console.error(`Update error for ${r.id}:`, updateErr);
      } else {
        updated++;
      }
    }

    if ((i + 1) % 100 === 0) console.log(`  Processed ${i + 1}/${sorted.length}...`);
  }

  console.log(`Updated ${updated} reports`);

  // Verify
  const { data: verify } = await supabase
    .from("quality_reports")
    .select("risk_level, status")
    .order("created_at", { ascending: false })
    .limit(10);

  console.log("Top 10 after fix:", verify?.map(r => `${r.risk_level}/${r.status}`));
}

main().catch(console.error);
