// CLAUDE LANE — Proof Center live stats.
//
// The /proof-center page's own footer says "Never hardcode this list --
// read it live" (corpus/programbench/eval_index.json is the named source
// of truth) while the page was, until this command existed, 100%
// hardcoded constants. This command reads the real, current corpus file
// so the page's headline numbers can never silently drift from reality
// again. Read-only: never writes eval_index.json, never runs an eval,
// never calls a model.

use std::fs;

use crate::ipc_hive::project_root;

#[derive(serde::Serialize)]
pub struct ProgramBenchProofStats {
    pub official_locks: u32,
    pub reference_archives: u32,
    pub total_entries_tracked: u32,
    pub source: String,
}

#[tauri::command]
pub fn get_programbench_proof_stats() -> Result<ProgramBenchProofStats, String> {
    let path = project_root()
        .join("corpus")
        .join("programbench")
        .join("eval_index.json");
    let text = fs::read_to_string(&path)
        .map_err(|e| format!("could not read {}: {e}", path.display()))?;
    let value: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("malformed eval_index.json: {e}"))?;
    let entries = value
        .as_array()
        .ok_or_else(|| "eval_index.json is not a JSON array".to_string())?;

    let mut official_locks: u32 = 0;
    let mut reference_archives: u32 = 0;
    for entry in entries {
        if entry.get("official_full_suite_resolved").and_then(|v| v.as_bool()) == Some(true) {
            official_locks += 1;
        }
        if entry.get("status").and_then(|v| v.as_str()) == Some("native_rebuild") {
            reference_archives += 1;
        }
    }

    Ok(ProgramBenchProofStats {
        official_locks,
        reference_archives,
        total_entries_tracked: entries.len() as u32,
        source: "corpus/programbench/eval_index.json".to_string(),
    })
}
