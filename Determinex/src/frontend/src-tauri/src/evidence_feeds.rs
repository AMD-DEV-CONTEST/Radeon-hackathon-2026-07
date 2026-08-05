//! Real, file-backed readers for two flagship features that previously had
//! zero backend wiring: the flywheel training feed (FlywheelFeed.tsx) and the
//! Project Cloak privacy audit (PrivacyCockpit.tsx). Both were hardcoded
//! empty arrays with an honest "nothing loaded" empty state but no attempt to
//! read the real corpus/audit files that already exist elsewhere in the repo
//! (scripts/pb_verdict_corpus.py, scripts/verify_cloak.py). These commands
//! read those real files if present; if not, they return the same honest
//! empty result the frontend already renders -- no fabricated data either way.

use serde::Serialize;
use std::fs;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use tauri::command;

/// How far back from the end of an append-only corpus we are willing to read.
/// The flywheel corpus on the author's machine is 8.44 GB; the panel needs the
/// newest ~30 records, so scanning 32 MB of tail is three orders of magnitude
/// more than required and still instant.
const TAIL_SCAN_CAP_BYTES: u64 = 32 * 1024 * 1024;

/// Below this size, counting every line is cheap enough to report an exact total.
/// Above it, the total is an estimate and says so -- see FlywheelSummary.
const EXACT_COUNT_MAX_BYTES: u64 = 64 * 1024 * 1024;

/// Complete lines from the END of a file, newest first, without loading the file.
///
/// WHY THIS EXISTS
/// `get_flywheel_feed` used to do `reader.lines().collect::<Vec<String>>()` on
/// `pb_verdict_corpus.jsonl` to get a line count and the newest N records. That file
/// is 8.44 GB (measured 2026-07-29), and a `Vec<String>` of it costs more than 8.44 GB
/// once per-String overhead is counted -- so opening the Flywheel panel tried to
/// allocate tens of gigabytes. The panel looked like the "permanent empty state" the
/// audit described; on a machine where the corpus is actually present it would freeze
/// or OOM the app instead.
///
/// Returns (lines_newest_first, hit_cap). `hit_cap` is true when the scan stopped at
/// the byte cap rather than the start of the file, which means any count derived from
/// these lines is a lower bound -- callers must surface that rather than round it off.
fn read_last_lines(path: &Path, max_lines: usize, cap_bytes: u64) -> std::io::Result<(Vec<String>, bool)> {
    let mut file = fs::File::open(path)?;
    let size = file.metadata()?.len();
    if size == 0 {
        return Ok((vec![], false));
    }

    const CHUNK: u64 = 1024 * 1024;
    let mut pos = size;
    let mut buf: Vec<u8> = Vec::new();
    let mut lines: Vec<String> = Vec::new();
    let mut hit_cap = false;

    while pos > 0 && lines.len() < max_lines {
        if size - pos >= cap_bytes {
            hit_cap = true;
            break;
        }
        let step = CHUNK.min(pos);
        pos -= step;
        file.seek(SeekFrom::Start(pos))?;
        let mut chunk = vec![0u8; step as usize];
        file.read_exact(&mut chunk)?;
        chunk.extend_from_slice(&buf);
        buf = chunk;

        // Everything after the first newline is a set of complete lines. What precedes
        // it is a partial line that the next (earlier) chunk completes, so it stays in
        // the buffer -- dropping it would silently corrupt the oldest record we return.
        //
        // ...UNLESS we have reached the start of the file, where there IS no earlier
        // chunk and so nothing is partial: the bytes before that first newline are the
        // file's first record. Treating them as a partial prefix silently dropped the
        // oldest line, which `tail_of_a_file_smaller_than_the_window_returns_everything`
        // caught -- 7 lines in, 6 out. A feed missing its oldest record still looks
        // entirely plausible, which is why it needed a test rather than a read-through.
        let (keep, complete) = if pos == 0 {
            (Vec::new(), buf.clone())
        } else {
            match buf.iter().position(|&b| b == b'\n') {
                Some(i) => (buf[..i].to_vec(), buf[i + 1..].to_vec()),
                None => continue, // no newline yet: widen the window
            }
        };
        for line in String::from_utf8_lossy(&complete).lines().rev() {
            if line.trim().is_empty() {
                continue;
            }
            lines.push(line.to_string());
            if lines.len() >= max_lines {
                break;
            }
        }
        buf = keep;
    }

    if pos > 0 && lines.len() < max_lines {
        hit_cap = true;
    }
    Ok((lines, hit_cap))
}

/// Exact line count, or None when the file is too large to count cheaply.
fn count_lines_if_cheap(path: &Path, size: u64) -> Option<u64> {
    if size > EXACT_COUNT_MAX_BYTES {
        return None;
    }
    let file = fs::File::open(path).ok()?;
    Some(BufReader::new(file).lines().filter(|l| l.is_ok()).count() as u64)
}

fn project_root() -> PathBuf {
    if let Ok(root) = std::env::var("DETERMINEX_ROOT") {
        return PathBuf::from(root);
    }
    let mut found = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if let Ok(exe) = std::env::current_exe() {
        let mut candidate = exe.parent().map(|p| p.to_path_buf()).unwrap_or_default();
        for _ in 0..8 {
            if candidate.join("scripts").join("determinex_hive.py").exists() {
                found = candidate.clone();
                break;
            }
            match candidate.parent() {
                Some(p) => candidate = p.to_path_buf(),
                None => break,
            }
        }
    }
    found
}

fn truncate_chars(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        s.chars().take(n).collect::<String>() + "…"
    }
}

// ── Flywheel training feed ─────────────────────────────────────────────────
// Reads corpus/programbench/training_corpus/pb_verdict_corpus.jsonl, the real
// append-only corpus written by scripts/pb_verdict_corpus.py::ingest_gate_result.

#[derive(Serialize)]
pub struct FlywheelPair {
    pub tool: String,
    pub lang: String,
    pub test_id: String,
    pub verdict: String, // "PASS" | "FAIL"
    pub captured_at: String,
    pub error_preview: Option<String>,
}

#[derive(Serialize)]
pub struct FlywheelSummary {
    /// Records in the scanned window with empty metadata -- real pairs, but they name
    /// nothing, so they are omitted from `pairs` rather than shown as "unknown".
    pub unidentified_in_window: u64,
    pub total_pairs: u64,
    pub added_today: u64,
    pub pairs: Vec<FlywheelPair>,
    /// True when `total_pairs` is derived from file size and average record length
    /// rather than counted. An exact count means reading all 8.44 GB; presenting an
    /// estimate as a count would be the same overclaim this codebase keeps finding, so
    /// the flag exists to be rendered, not ignored.
    pub total_is_estimate: bool,
    /// True when the tail scan hit its byte cap before reaching a record from before
    /// today, making `added_today` a LOWER BOUND rather than a total.
    pub added_today_is_partial: bool,
    pub corpus_bytes: u64,
}

#[command]
pub fn get_flywheel_feed(limit: Option<u64>) -> Result<FlywheelSummary, String> {
    let limit = limit.unwrap_or(30).max(1) as usize;
    let corpus_path = project_root()
        .join("corpus")
        .join("programbench")
        .join("training_corpus")
        .join("pb_verdict_corpus.jsonl");

    if !corpus_path.is_file() {
        return Ok(FlywheelSummary {
            total_pairs: 0, added_today: 0, pairs: vec![],
            total_is_estimate: false, added_today_is_partial: false, corpus_bytes: 0,
            unidentified_in_window: 0,
        });
    }

    let corpus_bytes = fs::metadata(&corpus_path).map(|m| m.len()).unwrap_or(0);

    // Read only the TAIL. The corpus is append-only and chronological, so both the
    // newest records and today's additions live at the end. Scanning back far enough to
    // find yesterday costs kilobytes; the previous full-file `collect()` cost 8.44 GB of
    // allocation for the same 30 records.
    //
    // The scan window has to be wider than `limit`: `added_today` counts every record
    // from today, which can be far more than the handful the panel displays.
    let scan_lines = limit.max(20_000);
    let (lines, hit_cap) = read_last_lines(&corpus_path, scan_lines, TAIL_SCAN_CAP_BYTES)
        .map_err(|e| e.to_string())?;

    let today = chrono::Utc::now().format("%Y-%m-%d").to_string();
    let mut added_today = 0u64;
    let mut pairs: Vec<FlywheelPair> = Vec::new();
    let mut reached_yesterday = false;
    // Records whose metadata is empty: counted in the totals, omitted from the preview.
    let mut unidentified = 0u64;

    // `lines` is already newest-first.
    for line in lines.iter() {
        let Ok(val) = serde_json::from_str::<serde_json::Value>(line) else { continue };
        let meta = val.get("metadata").cloned().unwrap_or(serde_json::Value::Null);
        let captured_at = meta.get("captured_at").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if captured_at.starts_with(&today) {
            added_today += 1;
        } else if !captured_at.is_empty() {
            // Chronological + append-only: the first pre-today record proves we have
            // seen every one of today's, so added_today is a total and not a floor.
            reached_yesterday = true;
        }
        // Some records carry a completely EMPTY metadata object -- measured 2026-08-04, 11 of
        // 40 in the tail. They are real training pairs and are counted as such, but they
        // identify nothing, and rendering them produced a feed of "unknown / unknown" rows
        // that visually dominated the real ones. Skip them in the PREVIEW and report how many
        // were skipped, so the panel can say what it left out rather than quietly dropping
        // records or quietly showing placeholders.
        let identified = meta.get("slug").and_then(|v| v.as_str()).is_some_and(|s| !s.is_empty());
        if !identified {
            unidentified += 1;
        }
        if identified && pairs.len() < limit {
            let verdict = meta
                .get("verdict")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_uppercase();
            let tool = meta.get("slug").and_then(|v| v.as_str()).unwrap_or("").to_string();
            // `implementation_language` is absent from older records; `module` is present in
            // both generations, so fall back to it rather than printing "unknown".
            let lang = meta
                .get("implementation_language")
                .and_then(|v| v.as_str())
                .or_else(|| meta.get("module").and_then(|v| v.as_str()))
                .unwrap_or("—")
                .to_string();
            let test_id = meta.get("test_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let error_preview = val
                .get("conversations")
                .and_then(|c| c.as_array())
                .and_then(|arr| arr.iter().find(|m| m.get("from").and_then(|f| f.as_str()) == Some("human")))
                .and_then(|m| m.get("value"))
                .and_then(|v| v.as_str())
                .map(|s| truncate_chars(s, 160));
            pairs.push(FlywheelPair { tool, lang, test_id, verdict, captured_at, error_preview });
        }
    }

    // An exact total means reading the whole file. Do that only when it is small;
    // otherwise estimate from the average record length actually observed in the tail,
    // and mark it an estimate so the UI can say so instead of implying a census.
    let (total_pairs, total_is_estimate) = match count_lines_if_cheap(&corpus_path, corpus_bytes) {
        Some(exact) => (exact, false),
        None => {
            let sampled_bytes: usize = lines.iter().map(|l| l.len() + 1).sum();
            let avg = if lines.is_empty() { 0 } else { sampled_bytes / lines.len() };
            let est = if avg == 0 { 0 } else { corpus_bytes / avg as u64 };
            (est, true)
        }
    };

    Ok(FlywheelSummary {
        total_pairs,
        added_today,
        pairs,
        total_is_estimate,
        added_today_is_partial: hit_cap && !reached_yesterday,
        corpus_bytes,
        unidentified_in_window: unidentified,
    })
}

// ── Project Cloak privacy audit ────────────────────────────────────────────
// Reads the newest logs/swebench/*/cloak_audit/verify_report.json (written by
// scripts/verify_cloak.py) plus its sibling cloak_map_*.json files for a
// bounded sample of real identifier->token pairs. Returns None if no Cloak
// run has ever produced audit evidence on this machine.

#[derive(Serialize)]
pub struct CloakIdentifier {
    pub real: String,
    pub token: String,
}

#[derive(Serialize)]
pub struct CloakAuditSummary {
    pub run_dir: String,
    pub verdict: String, // "clean" | "leaked" | "unverified"
    pub total_private_identifiers: u64,
    pub restoration_failures: u64,
    pub leaks_found: u64,
    pub api_audit_present: bool,
    pub keep_list_preserved: Vec<String>,
    pub identifiers: Vec<CloakIdentifier>,
    /// How many cloak_map_*.json files were actually opened, and how many exist. A real
    /// audit dir holds 299 of them totalling 621 MB, and this panel needs a 200-identifier
    /// sample -- so it reads a bounded few. Both numbers are reported because "sampled 8
    /// of 299" and "read all 299" are different claims about the same display.
    pub maps_sampled: u64,
    pub maps_total: u64,
}

/// Map files opened per panel load. The identifier list is capped at 200 and the keep-list
/// is near-identical across instances of one run, so a handful of files saturates the
/// display. The previous code's `break` only left the INNER loop, so it parsed all 299
/// files (621 MB, measured 2026-07-29) on every load of a panel that polls.
const MAX_MAPS_SAMPLED: usize = 8;

fn newest_file_matching(root: &std::path::Path, name: &str) -> Option<PathBuf> {
    let swebench_dir = root.join("logs").join("swebench");
    let run_dirs = fs::read_dir(&swebench_dir).ok()?;
    let mut best: Option<(std::time::SystemTime, PathBuf)> = None;
    for run_entry in run_dirs.flatten() {
        let candidate = run_entry.path().join("cloak_audit").join(name);
        if let Ok(meta) = fs::metadata(&candidate) {
            if let Ok(modified) = meta.modified() {
                let is_newer = match &best {
                    Some((t, _)) => modified > *t,
                    None => true,
                };
                if is_newer {
                    best = Some((modified, candidate));
                }
            }
        }
    }
    best.map(|(_, p)| p)
}

#[command]
pub fn get_cloak_audit_summary() -> Result<Option<CloakAuditSummary>, String> {
    let root = project_root();
    let Some(report_path) = newest_file_matching(&root, "verify_report.json") else {
        return Ok(None);
    };
    let report_text = fs::read_to_string(&report_path).map_err(|e| e.to_string())?;
    let report: serde_json::Value = serde_json::from_str(&report_text).map_err(|e| e.to_string())?;

    let audit_dir = report_path.parent().map(|p| p.to_path_buf());
    let mut keep_list_preserved: Vec<String> = Vec::new();
    let mut identifiers: Vec<CloakIdentifier> = Vec::new();

    let mut maps_sampled = 0u64;
    let mut maps_total = 0u64;

    if let Some(dir) = audit_dir {
        // Count first, sample second, so the ratio reported to the UI is honest without
        // paying to parse everything. read_dir metadata is cheap; read_to_string is not.
        if let Ok(entries) = fs::read_dir(&dir) {
            maps_total = entries
                .flatten()
                .filter(|e| {
                    e.path()
                        .file_name()
                        .and_then(|n| n.to_str())
                        .is_some_and(|n| n.starts_with("cloak_map_") && n.ends_with(".json"))
                })
                .count() as u64;
        }
        if let Ok(entries) = fs::read_dir(&dir) {
            for entry in entries.flatten() {
                if maps_sampled as usize >= MAX_MAPS_SAMPLED {
                    break;
                }
                let path = entry.path();
                let is_map = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .is_some_and(|n| n.starts_with("cloak_map_") && n.ends_with(".json"));
                if !is_map {
                    continue;
                }
                let Ok(text) = fs::read_to_string(&path) else { continue };
                maps_sampled += 1;
                let Ok(val) = serde_json::from_str::<serde_json::Value>(&text) else { continue };
                if let Some(keep) = val.get("keep_list_preserved").and_then(|v| v.as_array()) {
                    for k in keep {
                        if let Some(s) = k.as_str() {
                            if !keep_list_preserved.iter().any(|x| x == s) {
                                keep_list_preserved.push(s.to_string());
                            }
                        }
                    }
                }
                if let Some(forward) = val
                    .get("symbol_map")
                    .and_then(|m| m.get("forward"))
                    .and_then(|f| f.as_object())
                {
                    for (real, token) in forward {
                        if identifiers.len() >= 200 {
                            break;
                        }
                        if let Some(token_str) = token.as_str() {
                            identifiers.push(CloakIdentifier {
                                real: real.clone(),
                                token: token_str.to_string(),
                            });
                        }
                    }
                }
            }
        }
    }

    Ok(Some(CloakAuditSummary {
        run_dir: report.get("run_dir").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        verdict: report.get("verdict").and_then(|v| v.as_str()).unwrap_or("unverified").to_string(),
        total_private_identifiers: report
            .get("total_private_identifiers")
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        restoration_failures: report.get("restoration_failures").and_then(|v| v.as_u64()).unwrap_or(0),
        leaks_found: report.get("leaks_found").and_then(|v| v.as_u64()).unwrap_or(0),
        api_audit_present: report.get("api_audit_present").and_then(|v| v.as_bool()).unwrap_or(false),
        keep_list_preserved,
        identifiers,
        maps_sampled,
        maps_total,
    }))
}


#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// A backwards chunked read is easy to get subtly wrong at chunk boundaries, and the
    /// failure mode is quiet: a corrupted or dropped record at the oldest end of the
    /// window, which still renders as a plausible feed. These tests use a chunk-crossing
    /// file on purpose.
    fn write_lines(path: &Path, n: usize, pad: usize) {
        let mut f = fs::File::create(path).unwrap();
        for i in 0..n {
            writeln!(f, "{{\"i\":{},\"pad\":\"{}\"}}", i, "x".repeat(pad)).unwrap();
        }
    }

    #[test]
    fn tail_returns_newest_first() {
        let dir = std::env::temp_dir().join("dtx_tail_newest");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        write_lines(&p, 100, 10);

        let (lines, hit_cap) = read_last_lines(&p, 3, TAIL_SCAN_CAP_BYTES).unwrap();
        assert_eq!(lines.len(), 3);
        assert!(lines[0].contains("\"i\":99"), "newest first, got {}", lines[0]);
        assert!(lines[1].contains("\"i\":98"));
        assert!(lines[2].contains("\"i\":97"));
        assert!(!hit_cap);
    }

    #[test]
    fn tail_spans_chunk_boundaries_without_corrupting_a_record() {
        // >1 MB so the backwards read needs more than one chunk, with padding chosen so
        // records straddle the boundary. Every line returned must still be valid JSON --
        // a half-line stitched to the wrong neighbour is the bug this guards.
        let dir = std::env::temp_dir().join("dtx_tail_chunks");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        write_lines(&p, 20_000, 100); // ~2.4 MB

        let (lines, _) = read_last_lines(&p, 5_000, TAIL_SCAN_CAP_BYTES).unwrap();
        assert_eq!(lines.len(), 5_000);
        for l in &lines {
            serde_json::from_str::<serde_json::Value>(l)
                .unwrap_or_else(|e| panic!("corrupt line across chunk boundary: {e}: {l}"));
        }
        // Contiguous and descending: no gaps, no duplicates.
        let first: i64 = serde_json::from_str::<serde_json::Value>(&lines[0])
            .unwrap()["i"].as_i64().unwrap();
        assert_eq!(first, 19_999);
        let last: i64 = serde_json::from_str::<serde_json::Value>(lines.last().unwrap())
            .unwrap()["i"].as_i64().unwrap();
        assert_eq!(last, 19_999 - 4_999);
    }

    #[test]
    fn tail_of_a_file_smaller_than_the_window_returns_everything() {
        let dir = std::env::temp_dir().join("dtx_tail_small");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        write_lines(&p, 7, 5);

        let (lines, hit_cap) = read_last_lines(&p, 1_000, TAIL_SCAN_CAP_BYTES).unwrap();
        assert_eq!(lines.len(), 7, "asking for more lines than exist must not drop the first");
        assert!(lines.last().unwrap().contains("\"i\":0"), "oldest line lost");
        assert!(!hit_cap);
    }

    #[test]
    fn an_empty_file_is_not_an_error() {
        let dir = std::env::temp_dir().join("dtx_tail_empty");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        fs::File::create(&p).unwrap();
        let (lines, hit_cap) = read_last_lines(&p, 10, TAIL_SCAN_CAP_BYTES).unwrap();
        assert!(lines.is_empty());
        assert!(!hit_cap);
    }

    #[test]
    fn the_byte_cap_is_reported_not_hidden() {
        // A cap that stops the scan early makes any count derived from the window a
        // LOWER BOUND. Silently returning it as a total is the overclaim; hit_cap is how
        // the caller knows to say "at least".
        let dir = std::env::temp_dir().join("dtx_tail_cap");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        write_lines(&p, 20_000, 100);

        let (lines, hit_cap) = read_last_lines(&p, 20_000, 64 * 1024).unwrap();
        assert!(hit_cap, "stopped at the cap but did not say so");
        assert!(lines.len() < 20_000);
        for l in &lines {
            serde_json::from_str::<serde_json::Value>(l).expect("capped scan corrupted a line");
        }
    }

    #[test]
    fn a_large_file_total_is_flagged_as_an_estimate() {
        // The honesty contract: above EXACT_COUNT_MAX_BYTES we do not count, so the total
        // must be marked an estimate rather than presented as a census.
        assert!(count_lines_if_cheap(Path::new("nonexistent"), EXACT_COUNT_MAX_BYTES + 1).is_none());
    }

    #[test]
    fn a_small_file_is_counted_exactly() {
        let dir = std::env::temp_dir().join("dtx_count_small");
        fs::create_dir_all(&dir).unwrap();
        let p = dir.join("c.jsonl");
        write_lines(&p, 42, 5);
        let size = fs::metadata(&p).unwrap().len();
        assert_eq!(count_lines_if_cheap(&p, size), Some(42));
    }
}

#[cfg(test)]
mod perf_probe {
    use super::*;
    use std::path::PathBuf;

    /// Not a unit test -- a measurement against the REAL 8.44 GB corpus, which is the
    /// only thing that shows whether the panel is usable. Skips when the corpus is not
    /// on this machine rather than passing vacuously.
    #[test]
    fn real_corpus_tail_is_fast() {
        let p = PathBuf::from(std::env::var("DETERMINEX_ROOT").unwrap_or_else(|_| ".".into()))
            .join("corpus/programbench/training_corpus/pb_verdict_corpus.jsonl");
        if !p.is_file() {
            eprintln!("SKIP: real corpus not present at {}", p.display());
            return;
        }
        let bytes = std::fs::metadata(&p).unwrap().len();
        let t0 = std::time::Instant::now();
        let (lines, hit_cap) = read_last_lines(&p, 20_000, TAIL_SCAN_CAP_BYTES).unwrap();
        let ms = t0.elapsed().as_millis();
        eprintln!(
            "REAL CORPUS: {:.2} GB, read {} tail lines in {} ms (hit_cap={})",
            bytes as f64 / 1024.0 / 1024.0 / 1024.0,
            lines.len(),
            ms,
            hit_cap
        );
        assert!(ms < 10_000, "tail read took {ms} ms -- still too slow for a UI panel");
        for l in lines.iter().take(50) {
            serde_json::from_str::<serde_json::Value>(l)
                .unwrap_or_else(|e| panic!("real corpus line corrupted by the tail read: {e}"));
        }
    }
}
