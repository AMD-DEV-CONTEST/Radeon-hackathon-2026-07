use axum::{
    extract::{Json, State},
    http::StatusCode,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::info;

use crate::{paths, AppState};
use forge_test_lab::schemas::ResearchMission;
use forge_test_lab::worker::TestLabCoordinator;

#[derive(Deserialize)]
pub struct V3DemoRequest {
    #[serde(default)]
    pub admin_password: String,
    #[serde(default)]
    pub mission_note: String,
}

#[derive(Serialize)]
struct StageRecord {
    stage: String,
    implementation_path: String,
    start_unix: u64,
    end_unix: u64,
    input_hash: String,
    output_hash: String,
    status: String,
    notes: String,
}

#[derive(Serialize)]
struct ChainOfCustodyManifest {
    mission_id: String,
    run_id: String,
    forge_version: String,
    v2_baseline_commit: String,
    v3_integration_commit: String,
    knowledge_repository_hash: String,
    stage_order: Vec<String>,
    stages: Vec<StageRecord>,
    model_identity: String,
    worker_identity: String,
    backend_identity: String,
    validator_outcome: String,
    execution_mode: String,
    artifact_paths: Vec<String>,
    artifact_hashes: Vec<(String, String)>,
    final_human_review_state: String,
    failures: Vec<String>,
    limitations: Vec<String>,
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

fn file_hash(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|e| format!("failed to read {}: {}", path.display(), e))?;
    Ok(sha256_hex(&bytes))
}

fn read_git_rev(repo: &str, rev: &str) -> String {
    let out = std::process::Command::new("git")
        .args(["-C", repo, "rev-parse", rev])
        .output();
    match out {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => "unknown".to_string(),
    }
}

fn knowledge_hash() -> String {
    let repo = "/var/cesarops/forge-knowledge-repo";
    let mut entries: Vec<PathBuf> = Vec::new();
    if let Ok(read_dir) = fs::read_dir(repo) {
        for entry in read_dir.flatten() {
            let p = entry.path();
            if p.is_file() {
                entries.push(p);
            }
        }
    }

    // Include key category files recursively for a stable bounded hash
    for cat in ["canonical", "evidence", "lessons", "research"] {
        let cat_path = Path::new(repo).join(cat);
        if let Ok(rd) = fs::read_dir(&cat_path) {
            for e in rd.flatten() {
                let p = e.path();
                if p.is_file() {
                    entries.push(p);
                }
            }
        }
    }

    entries.sort();
    let mut hasher = Sha256::new();
    for p in entries {
        if let Ok(content) = fs::read(&p) {
            hasher.update(p.to_string_lossy().as_bytes());
            hasher.update(&content);
        }
    }
    hex::encode(hasher.finalize())
}

fn artifact_paths(base: &str) -> Vec<(String, PathBuf)> {
    vec![
        (
            "EvidenceReport".to_string(),
            Path::new(base).join("EvidenceReport.json"),
        ),
        (
            "QualificationDecision".to_string(),
            Path::new(base).join("QualificationDecision.json"),
        ),
        (
            "EvidenceLayerCandidate".to_string(),
            Path::new(base).join("EvidenceLayerCandidate.json"),
        ),
    ]
}

pub async fn run_aircraft_test_lab_demo(
    State(_state): State<AppState>,
    Json(req): Json<V3DemoRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let required = std::env::var("FORGE_ADMIN_PASSWORD").unwrap_or_default();
    if !required.is_empty() && req.admin_password != required {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "admin password required"})),
        ));
    }

    let started = now_unix();
    let mission_id = format!("mission-aircraft-v3-{}", started);
    let run_id = format!("run-{}", started);
    let forge_dir = paths::forge_dir();
    let fixture_dir = format!(
        "{}/core/forge-test-lab/fixtures/aircraft-search-grid-v1",
        forge_dir
    );

    if !Path::new(&fixture_dir).exists() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "error": "fixture directory missing",
                "fixture_dir": fixture_dir
            })),
        ));
    }

    let mut stages: Vec<StageRecord> = Vec::new();

    let stage1_start = now_unix();
    let knowledge_digest = knowledge_hash();
    let mission = ResearchMission {
        mission_id: mission_id.clone(),
        research_question: "Aircraft Test Lab V3 demonstration mission".to_string(),
        target_domain: "aircraft-search-grid".to_string(),
        known_positive_sites: vec!["SITE-001".to_string(), "SITE-002".to_string()],
        negative_control_strategy: "Matched terrain controls".to_string(),
        allowed_sources: vec![
            "CanonicalKnowledgeRepo".to_string(),
            "Qdrant_Wayfinder".to_string(),
        ],
        allowed_tools: vec![
            "ContextCompiler".to_string(),
            "InferenceBackend".to_string(),
        ],
        evaluation_metrics: vec![
            "TargetRankAfter".to_string(),
            "NegativeControlRejection".to_string(),
        ],
        stop_condition: "Produce Human Review package".to_string(),
        human_constraints: "DerivedFixtureMetrics only. No live imagery.".to_string(),
    };
    let mission_hash = forge_test_lab::schemas::deterministic_hash(&mission);
    stages.push(StageRecord {
        stage: "MissionSpec".to_string(),
        implementation_path: "forge_src/v3_slice.rs::run_aircraft_test_lab_demo".to_string(),
        start_unix: stage1_start,
        end_unix: now_unix(),
        input_hash: mission_hash.clone(),
        output_hash: mission_hash.clone(),
        status: "ok".to_string(),
        notes: if req.mission_note.is_empty() {
            "Run Forge V3 Aircraft Test Lab Demo".to_string()
        } else {
            req.mission_note.clone()
        },
    });

    let stage2_start = now_unix();
    let coordinator = TestLabCoordinator::new(&fixture_dir);
    let exec_result = coordinator.execute_mission(&mission);
    let stage2_end = now_unix();

    let report_base = format!("{}/reports/test-lab/aircraft-search-grid-v1", forge_dir);
    let artifacts = artifact_paths(&report_base);
    let mut artifact_hashes: Vec<(String, String)> = Vec::new();
    let mut artifact_paths_out: Vec<String> = Vec::new();

    let mut failures: Vec<String> = Vec::new();
    let mut final_human_review_state = "Revise".to_string();

    match exec_result {
        Ok(candidates) => {
            if !candidates.is_empty() {
                final_human_review_state = "AcceptForHumanReview".to_string();
            }
            for (name, path) in &artifacts {
                if path.exists() {
                    artifact_paths_out.push(path.display().to_string());
                    if let Ok(h) = file_hash(path) {
                        artifact_hashes.push((name.clone(), h));
                    }
                }
            }
        }
        Err(e) => {
            failures.push(format!("execution failed: {:?}", e));
        }
    }

    let output_hash = sha256_hex(
        serde_json::to_string(&artifact_hashes)
            .unwrap_or_default()
            .as_bytes(),
    );

    stages.push(StageRecord {
        stage: "TestLabExecution".to_string(),
        implementation_path:
            "core/forge-test-lab/src/worker.rs::TestLabCoordinator::execute_mission".to_string(),
        start_unix: stage2_start,
        end_unix: stage2_end,
        input_hash: mission_hash,
        output_hash,
        status: if failures.is_empty() {
            "ok".to_string()
        } else {
            "failed".to_string()
        },
        notes: "ExecutionMode=DerivedFixtureMetrics (no live imagery)".to_string(),
    });

    let manifest = ChainOfCustodyManifest {
        mission_id: mission_id.clone(),
        run_id: run_id.clone(),
        forge_version: "v3-phase1-vertical-slice".to_string(),
        v2_baseline_commit: std::env::var("FORGE_V2_BASELINE_SHA")
            .unwrap_or_else(|_| "942b0dc79a8413bd67aaac43e14ecd404a08e6d0".to_string()),
        v3_integration_commit: read_git_rev(&forge_dir, "HEAD"),
        knowledge_repository_hash: knowledge_digest,
        stage_order: stages.iter().map(|s| s.stage.clone()).collect(),
        stages,
        model_identity: "fixture-backed-test-lab".to_string(),
        worker_identity: "TestLabCoordinator/SandboxExecutorWorker/SkepticalReviewerWorker"
            .to_string(),
        backend_identity: "core/forge-test-lab".to_string(),
        validator_outcome: if failures.is_empty() {
            "pass".to_string()
        } else {
            "fail".to_string()
        },
        execution_mode: "DerivedFixtureMetrics".to_string(),
        artifact_paths: artifact_paths_out.clone(),
        artifact_hashes,
        final_human_review_state: final_human_review_state.clone(),
        failures,
        limitations: vec![
            "This validates orchestration, contracts, evidence generation, and gating.".to_string(),
            "It does not validate live aircraft imagery or sensor performance.".to_string(),
        ],
    };

    let manifest_dir = format!("{}/var/missions/v3/{}/{}", forge_dir, mission_id, run_id);
    if let Err(e) = fs::create_dir_all(&manifest_dir) {
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": format!("failed to create manifest dir: {}", e)})),
        ));
    }

    let manifest_path = format!("{}/chain_of_custody_manifest.json", manifest_dir);
    let manifest_json = serde_json::to_string_pretty(&manifest).unwrap_or_default();
    if let Err(e) = fs::write(&manifest_path, &manifest_json) {
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": format!("failed to write manifest: {}", e)})),
        ));
    }

    let trace_line = serde_json::json!({
        "ts": now_unix(),
        "mission_id": mission_id,
        "run_id": run_id,
        "stage": "HumanReviewBoundary",
        "state": final_human_review_state,
        "artifact_count": artifact_paths_out.len(),
        "manifest_path": manifest_path,
    });
    let trace_path = format!("{}/var/missions/forge_v3_admin_trace.jsonl", forge_dir);
    let mut trace_prev = fs::read_to_string(&trace_path).unwrap_or_default();
    trace_prev.push_str(&format!(
        "{}\n",
        serde_json::to_string(&trace_line).unwrap_or_default()
    ));
    let _ = fs::write(&trace_path, trace_prev);

    info!(
        "Forge V3 demo complete: manifest written at {}",
        manifest_path
    );

    Ok(Json(serde_json::json!({
        "mission_id": trace_line["mission_id"],
        "run_id": trace_line["run_id"],
        "plan_state": "Ready",
        "launch_state": "Executed",
        "current_stage": "HumanReviewBoundary",
        "validation_failures": manifest.failures,
        "execution_mode": "DerivedFixtureMetrics",
        "disclaimer": "This validates orchestration, contracts, evidence generation, and gating. It does not validate live aircraft imagery or sensor performance.",
        "final_human_review_state": trace_line["state"],
        "chain_of_custody_manifest": manifest_path,
        "admin_trace": trace_path,
        "artifacts": manifest.artifact_paths,
        "started_unix": started,
        "finished_unix": now_unix()
    })))
}
