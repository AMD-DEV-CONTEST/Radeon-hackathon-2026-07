/// release_status.rs — reads the live release-gate evidence collector output.
///
/// `MissionControlPanel`/`SuccessorRoadmapPanel` used to import a hand-baked TS
/// snapshot of this file (`releaseGateStatus.ts`), which drifts stale within
/// days of a fresh `determinex_release_gates.py` run (see CLAUDE.md's "Board
/// staleness protocol"). This command reads the real, current evidence file at
/// runtime so the frontend can show live gate status with the baked-in
/// snapshot only as a browser-mode/read-failure fallback.
use serde_json::Value;
use std::fs;

#[tauri::command]
/// Returns the newest `release_gates_*.json` evidence file VERBATIM.
///
/// Deliberately untyped, and this is the one place where that is the honest
/// answer: the file is written by the release-gate collector and its shape is
/// whatever that run produced. Declaring a struct here would silently DROP fields
/// from an evidence artifact, which is worse than leaving it dynamic -- the whole
/// point of the artifact is that it is a faithful record.
pub fn get_release_gate_status() -> Result<Value, String> {
    let dir = crate::ipc_hive::project_root()
        .join("assurance")
        .join("evidence")
        .join("determinex_release_gate_status");

    let mut candidates: Vec<_> = fs::read_dir(&dir)
        .map_err(|e| format!("Cannot read {}: {e}", dir.display()))?
        .flatten()
        .filter(|entry| {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            name.starts_with("release_gates_") && name.ends_with(".json")
        })
        .collect();

    if candidates.is_empty() {
        return Err(format!("No release_gates_*.json found in {}", dir.display()));
    }

    // Pick by the artifact's OWN `generated_at_utc`, not by mtime.
    //
    // WHY (changed 2026-07-29). This sorted by mtime, reasoning that "a future collector
    // run that writes a differently-dated filename is still picked up as current". The
    // flaw is that mtime does not track the run: a git checkout, a file copy, or a clone
    // rewrites it in whatever order it touches files. This tree already demonstrates the
    // drift -- release_gates_20260707.json carries an mtime of 2026-07-18, eleven days
    // after the run it describes. One `touch` of the older packet and the panel reports
    // July 7 gate status as current, silently, on the surface whose entire job is saying
    // whether the product is ready to ship. That is the "board staleness" failure CLAUDE.md
    // warns about ("silent drift is real"), pointed at release readiness.
    //
    // The embedded timestamp is authoritative: the collector writes it as part of the
    // record, so it survives copies. Filename is the tiebreak (the dates in
    // release_gates_YYYYMMDD.json sort chronologically), mtime the last resort -- which
    // also preserves the original intent for an artifact whose name carries no date.
    // Reading every candidate is cheap: these packets are ~13 KB.
    let mut best: Option<(String, String, Value)> = None;
    let mut last_err: Option<String> = None;
    for entry in &candidates {
        let name = entry.file_name().to_string_lossy().to_string();
        let content = match fs::read_to_string(entry.path()) {
            Ok(c) => c,
            Err(e) => {
                last_err = Some(format!("{name}: {e}"));
                continue;
            }
        };
        let value: Value = match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(e) => {
                last_err = Some(format!("{name}: {e}"));
                continue;
            }
        };
        let stamp = value
            .get("generated_at_utc")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let is_better = match &best {
            None => true,
            // Compare the embedded stamp first; fall back to the filename when a packet
            // omits it, so a stampless artifact never outranks a stamped one by accident.
            Some((best_stamp, best_name, _)) => {
                (stamp.as_str(), name.as_str()) > (best_stamp.as_str(), best_name.as_str())
            }
        };
        if is_better {
            best = Some((stamp, name, value));
        }
    }

    match best {
        Some((_, _, value)) => Ok(value),
        None => Err(format!(
            "No readable release_gates_*.json in {} ({})",
            dir.display(),
            last_err.unwrap_or_else(|| "unknown error".into())
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(dir_name: &str) -> PathBuf {
        let base = std::env::temp_dir().join(dir_name);
        let _ = fs::remove_dir_all(&base);
        let dir = base
            .join("assurance")
            .join("evidence")
            .join("determinex_release_gate_status");
        fs::create_dir_all(&dir).unwrap();
        base
    }

    fn write_packet(base: &PathBuf, name: &str, stamp: &str) {
        let dir = base
            .join("assurance")
            .join("evidence")
            .join("determinex_release_gate_status");
        let body = format!(
            r#"{{"schema_version":"determinex-release-gate-status-v1","generated_at_utc":"{stamp}","gates":[]}}"#
        );
        fs::write(dir.join(name), body).unwrap();
    }

    /// project_root() reads DETERMINEX_ROOT. Restore it so tests do not leak state into
    /// each other -- run with --test-threads=1 for the env-var swap to be sound.
    /// Serialises every test that reads or writes DETERMINEX_ROOT.
    ///
    /// Environment variables are per-PROCESS and cargo runs a test binary's tests on parallel
    /// threads, so `with_root` pointing the root at a fixture was visible to every other test at the
    /// same instant. Found 2026-07-31: `the_real_tree_reports_the_latest_collector_run` passed when
    /// run alone and failed in the full suite, with the panic moving between the read and the
    /// assertion depending on which thread won -- it was reading a fixture root, or none, instead of
    /// the working tree. Adding nine unrelated tests to this binary was enough to change the
    /// scheduling and surface it, which is the tell for a race rather than a stale fixture.
    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// Held across the whole body of a root-dependent test. A poisoned lock is recovered from
    /// rather than propagated: one failing test must not convert every sibling into a panic that
    /// hides the original failure.
    fn env_guard() -> std::sync::MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn with_root<T>(base: &PathBuf, f: impl FnOnce() -> T) -> T {
        let _lock = env_guard();
        let prev = std::env::var("DETERMINEX_ROOT").ok();
        std::env::set_var("DETERMINEX_ROOT", base);
        let out = f();
        match prev {
            Some(p) => std::env::set_var("DETERMINEX_ROOT", p),
            None => std::env::remove_var("DETERMINEX_ROOT"),
        }
        out
    }

    #[test]
    fn the_newest_run_wins_even_when_mtime_says_otherwise() {
        // THE regression. Selection used to sort by mtime, and mtime does not track the
        // run: a checkout or copy rewrites it arbitrarily. Here the OLDER packet is
        // written LAST, so mtime and the embedded timestamp disagree -- exactly the state
        // a `git checkout` of one file produces.
        let base = fixture("dtx_rs_mtime");
        write_packet(&base, "release_gates_20260728.json", "2026-07-28T17:35:59Z");
        std::thread::sleep(std::time::Duration::from_millis(60));
        write_packet(&base, "release_gates_20260707.json", "2026-07-07T12:11:54Z");

        let v = with_root(&base, || get_release_gate_status()).expect("should read a packet");
        assert_eq!(
            v.get("generated_at_utc").and_then(|s| s.as_str()),
            Some("2026-07-28T17:35:59Z"),
            "reported a superseded gate run as current because its file was touched later"
        );
    }

    #[test]
    fn a_packet_without_a_timestamp_never_outranks_one_with_it() {
        let base = fixture("dtx_rs_nostamp");
        write_packet(&base, "release_gates_20260728.json", "2026-07-28T17:35:59Z");
        let dir = base
            .join("assurance")
            .join("evidence")
            .join("determinex_release_gate_status");
        fs::write(
            dir.join("release_gates_29999999.json"),
            r#"{"schema_version":"determinex-release-gate-status-v1","gates":[]}"#,
        )
        .unwrap();

        let v = with_root(&base, || get_release_gate_status()).unwrap();
        assert_eq!(
            v.get("generated_at_utc").and_then(|s| s.as_str()),
            Some("2026-07-28T17:35:59Z"),
            "a stampless packet with a high filename outranked a real, stamped run"
        );
    }

    #[test]
    fn an_unparseable_packet_is_skipped_rather_than_fatal() {
        // One corrupt artifact must not blank the whole panel when a good one exists.
        let base = fixture("dtx_rs_corrupt");
        let dir = base
            .join("assurance")
            .join("evidence")
            .join("determinex_release_gate_status");
        fs::write(dir.join("release_gates_20260729.json"), "{ not json at all").unwrap();
        write_packet(&base, "release_gates_20260728.json", "2026-07-28T17:35:59Z");

        let v = with_root(&base, || get_release_gate_status()).expect("good packet should win");
        assert_eq!(
            v.get("generated_at_utc").and_then(|s| s.as_str()),
            Some("2026-07-28T17:35:59Z")
        );
    }

    #[test]
    fn all_packets_corrupt_is_an_error_not_an_empty_success() {
        // Returning Ok of something empty here would render as "no gates", which reads as
        // a clean board. An unreadable evidence set is not a clean board.
        let base = fixture("dtx_rs_allbad");
        let dir = base
            .join("assurance")
            .join("evidence")
            .join("determinex_release_gate_status");
        fs::write(dir.join("release_gates_20260729.json"), "{ nope").unwrap();
        let out = with_root(&base, || get_release_gate_status());
        assert!(out.is_err(), "expected an error, got {out:?}");
    }

    #[test]
    fn the_real_tree_reports_the_latest_collector_run() {
        // Measurement against the working tree, skipped loudly when absent. The frontend
        // falls back to a constant stamped 2026-07-08T12:11:54Z, so anything at or below
        // that means the panel is showing frozen data.
        // Held for the whole test: without it a sibling's `with_root` fixture is what
        // get_release_gate_status() below actually reads. See ENV_LOCK.
        let _lock = env_guard();
        let root = PathBuf::from(match std::env::var("DETERMINEX_ROOT") {
            Ok(r) => r,
            Err(_) => return,
        });
        if !root
            .join("assurance/evidence/determinex_release_gate_status")
            .is_dir()
        {
            eprintln!("SKIP: no gate evidence in {}", root.display());
            return;
        }
        let v = get_release_gate_status().expect("real tree should have a readable packet");
        let stamp = v.get("generated_at_utc").and_then(|s| s.as_str()).unwrap_or("");
        let gates = v.get("gates").and_then(|g| g.as_array()).map(|a| a.len()).unwrap_or(0);
        eprintln!("REAL GATES: {gates} gates, generated {stamp}");
        assert!(gates > 0, "a status report with no gates is not a report");
        assert!(
            stamp > "2026-07-08T12:11:54Z",
            "live status ({stamp}) is not newer than the hardcoded fallback it exists to replace"
        );
    }
}
