//! Rosetta projection weights: local status and on-demand fetch from HuggingFace.
//!
//! WHY THIS IS NATIVE RUST AND NOT A PYTHON CALL
//! ---------------------------------------------
//! `scripts/rosetta_hub.py` does the same job, but it is a REPO script -- it does
//! not exist in an installed copy. Every other "call a repo script" path in this
//! app turned out to be a tether that made a feature dev-only (see
//! `ipc_hive::hive_command`). Doing the download here, with `reqwest` which is
//! already a dependency, means the weights can be fetched by the shipped product.
//!
//! WHAT IT FETCHES
//! ---------------
//! Not the 1.68 GB `.pt` -- the exported `.npz` shards, 92-134 MB per model
//! architecture, which run on numpy alone. A user needs only the architectures
//! their models actually use, so the common case is one or two shards rather than
//! 839 MB.
//!
//! Every shard's SHA256 is recorded in the manifest and verified after download.
//! A truncated fetch of a 92 MB file is a realistic failure, and projecting through
//! a partial weight matrix would produce confident nonsense -- so a mismatch
//! deletes the file and reports it rather than leaving it on disk to be trusted.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::command;

const DEFAULT_REPO: &str = "darthceltic85/determinex-rosetta";
const MANIFEST_NAME: &str = "rosetta_npz_manifest.json";

fn npz_dir() -> PathBuf {
    dirs_home().join(".determinex").join("rosetta").join("npz")
}

fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

#[derive(Deserialize)]
struct ManifestShard {
    file: String,
    bytes: u64,
    sha256: String,
    dim: Option<u32>,
}

#[derive(Deserialize)]
struct Manifest {
    #[serde(default)]
    shards: std::collections::HashMap<String, ManifestShard>,
    d_rosetta: Option<u32>,
    storage_dtype: Option<String>,
}

#[derive(Serialize)]
pub struct ShardStatus {
    pub arch: String,
    pub file: String,
    pub bytes: u64,
    pub dim: Option<u32>,
    /// Present locally AND matching its recorded checksum.
    pub ready: bool,
    /// Present but the wrong bytes -- a failed download left behind.
    pub corrupt: bool,
}

#[derive(Serialize)]
pub struct RosettaStatus {
    /// True when a manifest is present, i.e. the app knows what CAN be fetched.
    pub manifest_present: bool,
    pub dir: String,
    pub repo: String,
    pub d_rosetta: Option<u32>,
    pub storage_dtype: Option<String>,
    pub shards: Vec<ShardStatus>,
    pub ready_count: usize,
    /// The legacy 1.68 GB checkpoint, if a dev checkout still has one. Reported so
    /// the UI can say WHICH projector would be used rather than implying the npz
    /// path is the only possibility.
    pub source_checkpoint_present: bool,
    pub note: String,
}

fn sha256_file(path: &std::path::Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    let mut h = Sha256::new();
    h.update(&bytes);
    Some(format!("{:x}", h.finalize()))
}

/// What projection weights are on this machine, and what could be fetched.
#[command]
pub fn rosetta_status() -> Result<RosettaStatus, String> {
    let dir = npz_dir();
    let pt = dirs_home().join(".determinex").join("rosetta").join("rosetta_v1.pt");
    let manifest_path = dir.join(MANIFEST_NAME);

    if !manifest_path.is_file() {
        return Ok(RosettaStatus {
            manifest_present: false,
            dir: dir.to_string_lossy().to_string(),
            repo: DEFAULT_REPO.to_string(),
            d_rosetta: None,
            storage_dtype: None,
            shards: Vec::new(),
            ready_count: 0,
            source_checkpoint_present: pt.is_file(),
            note: "No manifest yet. Fetch weights to enable latent projection between models."
                .to_string(),
        });
    }

    let raw = std::fs::read_to_string(&manifest_path)
        .map_err(|e| format!("cannot read {}: {e}", manifest_path.display()))?;
    let manifest: Manifest =
        serde_json::from_str(&raw).map_err(|e| format!("{MANIFEST_NAME} is not valid JSON: {e}"))?;

    let mut shards: Vec<ShardStatus> = manifest
        .shards
        .iter()
        .map(|(arch, s)| {
            let path = dir.join(&s.file);
            let (ready, corrupt) = if path.is_file() {
                match sha256_file(&path) {
                    Some(d) if d == s.sha256 => (true, false),
                    // Present and wrong. Reported as corrupt, NOT as ready -- a
                    // half-downloaded shard that projects is the failure mode this
                    // whole checksum path exists to prevent.
                    _ => (false, true),
                }
            } else {
                (false, false)
            };
            ShardStatus {
                arch: arch.clone(),
                file: s.file.clone(),
                bytes: s.bytes,
                dim: s.dim,
                ready,
                corrupt,
            }
        })
        .collect();
    shards.sort_by(|a, b| a.arch.cmp(&b.arch));
    let ready_count = shards.iter().filter(|s| s.ready).count();

    let note = if ready_count == 0 {
        "No architecture weights downloaded yet.".to_string()
    } else {
        format!("{ready_count} of {} architectures ready.", shards.len())
    };

    Ok(RosettaStatus {
        manifest_present: true,
        dir: dir.to_string_lossy().to_string(),
        repo: DEFAULT_REPO.to_string(),
        d_rosetta: manifest.d_rosetta,
        storage_dtype: manifest.storage_dtype,
        shards,
        ready_count,
        source_checkpoint_present: pt.is_file(),
        note,
    })
}

fn hf_token() -> Option<String> {
    for k in [
        "HF_TOKEN",
        "HUGGINGFACE_API_KEY",
        "HUGGINGFACE_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    ] {
        if let Ok(v) = std::env::var(k) {
            if !v.trim().is_empty() {
                return Some(v.trim().to_string());
            }
        }
    }
    None
}

async fn download(url: &str, dest: &std::path::Path, token: Option<&str>) -> Result<u64, String> {
    let client = reqwest::Client::builder()
        .build()
        .map_err(|e| format!("http client: {e}"))?;
    let mut req = client.get(url);
    if let Some(t) = token {
        req = req.bearer_auth(t);
    }
    let resp = req.send().await.map_err(|e| format!("GET {url}: {e}"))?;
    if !resp.status().is_success() {
        // 401/403 on a private repo is the single most likely failure, so name it
        // instead of returning a bare status code.
        let hint = match resp.status().as_u16() {
            401 | 403 => " (the repo is private -- set HF_TOKEN in .env)",
            404 => " (not found -- check the repo id and file name)",
            _ => "",
        };
        return Err(format!("{} returned {}{hint}", url, resp.status()));
    }
    let bytes = resp.bytes().await.map_err(|e| format!("reading {url}: {e}"))?;
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    std::fs::write(dest, &bytes).map_err(|e| format!("write {}: {e}", dest.display()))?;
    Ok(bytes.len() as u64)
}

#[derive(Serialize)]
pub struct FetchResult {
    pub fetched: Vec<String>,
    pub skipped: Vec<String>,
    pub failed: Vec<String>,
    pub bytes: u64,
}

/// Fetch the manifest, then the requested architectures' shards.
///
/// `arches` empty means "everything in the manifest", which is 839 MB -- the UI
/// should default to the architectures actually in use, not all of them.
#[command]
pub async fn rosetta_fetch(arches: Vec<String>, repo: Option<String>) -> Result<FetchResult, String> {
    let repo = repo.unwrap_or_else(|| DEFAULT_REPO.to_string());
    let dir = npz_dir();
    let token = hf_token();
    let base = format!("https://huggingface.co/{repo}/resolve/main");

    // Manifest first: it is the list of what exists and the source of the hashes
    // everything else is checked against.
    let manifest_path = dir.join(MANIFEST_NAME);
    download(&format!("{base}/{MANIFEST_NAME}"), &manifest_path, token.as_deref()).await?;
    let manifest: Manifest = serde_json::from_str(
        &std::fs::read_to_string(&manifest_path).map_err(|e| e.to_string())?,
    )
    .map_err(|e| format!("downloaded {MANIFEST_NAME} is not valid JSON: {e}"))?;

    let wanted: Vec<String> = if arches.is_empty() {
        manifest.shards.keys().cloned().collect()
    } else {
        arches
    };

    let mut out = FetchResult { fetched: vec![], skipped: vec![], failed: vec![], bytes: 0 };
    for arch in wanted {
        let Some(entry) = manifest.shards.get(&arch) else {
            out.failed.push(format!("{arch}: not in the manifest"));
            continue;
        };
        let dest = dir.join(&entry.file);
        if dest.is_file() && sha256_file(&dest).as_deref() == Some(entry.sha256.as_str()) {
            out.skipped.push(arch);
            continue;
        }
        match download(&format!("{base}/{}", entry.file), &dest, token.as_deref()).await {
            Ok(n) => {
                // Verify before declaring success. A shard that downloaded but does
                // not match is deleted: leaving it would mean the next status call
                // reports it corrupt forever, and worse, a caller that skips the
                // check would project through it.
                match sha256_file(&dest) {
                    Some(d) if d == entry.sha256 => {
                        out.bytes += n;
                        out.fetched.push(arch);
                    }
                    _ => {
                        let _ = std::fs::remove_file(&dest);
                        out.failed.push(format!("{arch}: checksum mismatch, discarded"));
                    }
                }
            }
            Err(e) => out.failed.push(format!("{arch}: {e}")),
        }
    }
    Ok(out)
}
