#![allow(dead_code)]

mod translator;
mod diagnostics;
mod tools;
mod memory;
mod hardware;
mod prompts;
mod loop_engine;
mod agent_dispatch;
mod validator;
mod paths;
mod cluster_store;
mod routing;
mod inference_client;
mod stream_lanes;

use axum::{
    extract::{Json, Path, State},
    response::Html,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{info, warn};

#[derive(Clone)]
pub struct AppState {
    pub conversation: Arc<Mutex<Vec<translator::Message>>>,
    pub config: Arc<ForgeConfig>,
    pub interrupt: Arc<std::sync::atomic::AtomicBool>,
    pub send_busy: Arc<std::sync::atomic::AtomicBool>,
    pub steering: Arc<Mutex<Vec<String>>>,
    pub lanes: stream_lanes::LaneStore,
}

#[derive(Clone)]
pub struct ForgeConfig {
    pub coder_url: String,      // 35B on P100s
    pub thinker_url: String,    // R1 on Xeon DDR4
    pub corrector_url: String,  // 14B Coder on 1070 (Marvin)
    pub nautivecs_url: String,
    pub wso_url: String,
    pub project_root: String,
    /// P1000 reference validator endpoint (cesarops2:5571)
    pub validator_url: String,
}

#[derive(Deserialize)]
struct SendRequest {
    message: String,
    /// lane-a | lane-b | lane-c
    #[serde(default)]
    lane: Option<String>,
}

#[derive(Deserialize)]
struct LaneRoleRequest {
    role: String,
}

#[derive(Serialize)]
struct SendResponse {
    response: String,
    tool_actions: Vec<String>,
    diagnosis: Option<String>,
}

async fn index() -> Html<&'static str> {
    Html(include_str!("index.html"))
}

async fn cluster_panel() -> Html<&'static str> {
    Html(include_str!("cluster_panel.html"))
}

async fn health() -> &'static str {
    r#"{"status":"ok","service":"cesarops-forge-v2","mode":"self-healing-translator"}"#
}

async fn send_message(
    State(state): State<AppState>,
    Json(req): Json<SendRequest>,
) -> Json<SendResponse> {
    let lane = req.lane.clone().unwrap_or_else(|| "lane-a".to_string());
    info!(
        "User [{}]: {}",
        lane,
        &req.message[..req.message.len().min(100)]
    );

    if state
        .send_busy
        .compare_exchange(
            false,
            true,
            std::sync::atomic::Ordering::AcqRel,
            std::sync::atomic::Ordering::Relaxed,
        )
        .is_err()
    {
        return Json(SendResponse {
            response: "[Forge busy] Another task is running. Stop or wait, then retry.".into(),
            tool_actions: vec![],
            diagnosis: None,
        });
    }
    state.interrupt.store(false, std::sync::atomic::Ordering::Relaxed);

    let role = routing::load_lanes_state()
        .lane_roles
        .get(&lane)
        .cloned()
        .unwrap_or_else(|| "general".to_string());
    let coder_url = routing::resolve_lane_coder_url(&lane);
    let coding_only = role == "coding";

    let ctx = loop_engine::RunContext {
        lane: Some(lane.clone()),
        coder_url: Some(coder_url),
        skip_thinker: coding_only,
        coding_only,
    };

    let result = loop_engine::run_with_context(&state, &req.message, ctx).await;
    state
        .send_busy
        .store(false, std::sync::atomic::Ordering::Relaxed);

    state
        .lanes
        .log(&lane, "done", &result.response[..result.response.len().min(80)])
        .await;

    info!(
        "Response [{}]: {}... (tools: {}, diagnosed: {})",
        lane,
        &result.response[..result.response.len().min(80)],
        result.tool_actions.len(),
        result.diagnosis.is_some()
    );

    Json(result)
}

async fn clear_lane(
    State(state): State<AppState>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let lane = body
        .get("lane")
        .and_then(|v| v.as_str())
        .unwrap_or("lane-a");
    state.lanes.clear_lane(lane).await;
    if lane == "lane-a" {
        state.conversation.lock().await.clear();
    }
    tools::reset_think_counter();
    state.interrupt.store(false, std::sync::atomic::Ordering::Relaxed);
    state.send_busy.store(false, std::sync::atomic::Ordering::Relaxed);
    Json(serde_json::json!({"message": format!("Lane {} cleared", lane)}))
}

async fn clear(State(state): State<AppState>) -> &'static str {
    let mut conv = state.conversation.lock().await;
    conv.clear();
    for lane in stream_lanes::LANE_IDS {
        state.lanes.clear_lane(lane).await;
    }
    tools::reset_think_counter();
    state.interrupt.store(false, std::sync::atomic::Ordering::Relaxed);
    state.send_busy.store(false, std::sync::atomic::Ordering::Relaxed);
    "Conversation cleared"
}

async fn interrupt(State(state): State<AppState>) -> &'static str {
    state.interrupt.store(true, std::sync::atomic::Ordering::Relaxed);
    info!("INTERRUPT signal received — will stop after current tool call");
    "Interrupt signal sent. Generation will stop after current round."
}

async fn steer(State(state): State<AppState>, Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let msg = body.get("message").and_then(|v| v.as_str()).unwrap_or("");
    if msg.is_empty() {
        return Json(serde_json::json!({"error": "message required"}));
    }
    let mut steering = state.steering.lock().await;
    steering.push(msg.to_string());
    info!("STEERING injected: {}", &msg[..msg.len().min(80)]);
    Json(serde_json::json!({"message": format!("Steering queued: {}", msg)}))
}

async fn monitor() -> Json<serde_json::Value> {
    Json(hardware::cluster_summary().await)
}

fn set_skip_corrector_config(disabled: bool) -> Result<(), String> {
    let mut table = cluster_store::read_config();
    let tuning = table
        .entry("tuning".to_string())
        .or_insert_with(|| toml::Value::Table(toml::Table::new()))
        .as_table_mut()
        .ok_or("Invalid [tuning] table")?;
    tuning.insert(
        "skip_corrector".to_string(),
        toml::Value::Boolean(disabled),
    );
    cluster_store::write_config(&table)
}

fn table_string_array(table: &toml::Table, key: &str) -> Vec<String> {
    table
        .get(key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

fn find_routing_preset(table: &toml::Table, preset_id: &str) -> Option<toml::Table> {
    table
        .get("routing_preset")
        .and_then(|v| v.as_array())
        .and_then(|arr| {
            arr.iter().find_map(|item| {
                let t = item.as_table()?;
                let id = t.get("id").and_then(|v| v.as_str())?;
                if id == preset_id {
                    Some(t.clone())
                } else {
                    None
                }
            })
        })
}

fn orchestration_url_for_action(table: &toml::Table, action: &str) -> Option<String> {
    let orchestration = table.get("orchestration")?.as_table()?;
    if action.contains("pamp") {
        orchestration
            .get("n8n_pamp_url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
    } else {
        orchestration
            .get("n8n_fleet_url")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
    }
}

fn resolve_project_dir(input: Option<&str>) -> String {
    let root = paths::project_root();
    let Some(dir) = input.filter(|s| !s.trim().is_empty()) else {
        return root;
    };
    if dir.starts_with('/') {
        dir.to_string()
    } else {
        format!("{}/{}", root, dir.trim_start_matches("./"))
    }
}

fn run_cargo_feedback(action: &str, project_dir: &str) -> serde_json::Value {
    let mut cmd = std::process::Command::new("cargo");
    match action {
        "cargo_test_feedback" => {
            cmd.arg("test").arg("--no-run");
        }
        _ => {
            cmd.arg("check");
        }
    }
    let output = cmd.current_dir(project_dir).output();
    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            serde_json::json!({
                "ok": out.status.success(),
                "exit_code": out.status.code(),
                "project_dir": project_dir,
                "stdout_tail": stdout.chars().rev().take(4000).collect::<String>().chars().rev().collect::<String>(),
                "stderr_tail": stderr.chars().rev().take(4000).collect::<String>().chars().rev().collect::<String>(),
            })
        }
        Err(e) => serde_json::json!({
            "ok": false,
            "project_dir": project_dir,
            "error": format!("failed to execute cargo command: {}", e),
        }),
    }
}

fn mcp_endpoint_from_config() -> Option<String> {
    let table = cluster_store::read_config();
    table
        .get("nicknames")
        .and_then(|v| v.as_table())
        .and_then(|nick| nick.get("mcp-local"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

// --- Preset API ---

async fn get_preset_config() -> Json<serde_json::Value> {
    let preset_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/preset.json";
    match std::fs::read_to_string(preset_path) {
        Ok(content) => {
            let val: serde_json::Value = serde_json::from_str(&content).unwrap_or_default();
            Json(val)
        }
        Err(_) => {
            // Default preset
            Json(serde_json::json!({
                "p100_mode": "unified",
                "gpu0_role": "coder",
                "gpu0_model": "",
                "gpu1_role": "kv-cache",
                "gpu1_model": "",
                "node_1070": "corrector",
                "node_1060": "thinker",
                "node_laptop": "idle",
                "active": true
            }))
        }
    }
}

async fn save_preset_config(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let preset_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/preset.json";
    match std::fs::write(preset_path, serde_json::to_string_pretty(&body).unwrap_or_default()) {
        Ok(_) => Json(serde_json::json!({"message": "CESAROPS configuration saved."})),
        Err(e) => Json(serde_json::json!({"error": format!("Failed to save preset: {}", e)})),
    }
}

async fn activate_preset() -> Json<serde_json::Value> {
    let preset_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/preset.json";
    let mut preset: serde_json::Value = match std::fs::read_to_string(preset_path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => serde_json::json!({"active": true}),
    };
    preset["active"] = serde_json::json!(true);
    let _ = std::fs::write(preset_path, serde_json::to_string_pretty(&preset).unwrap_or_default());
    info!("CESAROPS ACTIVATED - locking resources for SAR scanning");
    Json(serde_json::json!({"message": "CESAROPS activated. Resources locked for scanning."}))
}

async fn launch_preset() -> Json<serde_json::Value> {
    let preset_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/preset.json";
    let preset: serde_json::Value = match std::fs::read_to_string(preset_path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => return Json(serde_json::json!({"error": "No preset config saved. Save first."})),
    };

    // Stop all existing workers
    let _ = std::process::Command::new("bash")
        .arg("-c")
        .arg("pkill -f 'cesarops-inference.*--backend' ; pkill -f 'koboldcpp.*--model'")
        .output();

    info!("All workers stopped. Launching preset config...");

    let gpu0_model = preset.get("gpu0_model").and_then(|v| v.as_str()).unwrap_or("");
    let gpu0_role = preset.get("gpu0_role").and_then(|v| v.as_str()).unwrap_or("coder");
    let p100_mode = preset.get("p100_mode").and_then(|v| v.as_str()).unwrap_or("unified");

    let mut launched = Vec::new();

    // Launch GPU0 worker
    if !gpu0_model.is_empty() {
        let port = 5001;
        let cmd = format!(
            "nohup /home/cesarops/koboldcpp --model {} --port {} --usevulkan --gpulayers 99 > /tmp/preset_gpu0.log 2>&1 &",
            gpu0_model, port
        );
        let _ = std::process::Command::new("bash").arg("-c").arg(&cmd).output();
        launched.push(format!("GPU0 ({}): {} on port {}", gpu0_role, gpu0_model.split('/').last().unwrap_or_default(), port));
    }

    // Mark preset as active
    let mut active_preset = preset.clone();
    active_preset["active"] = serde_json::json!(true);
    let _ = std::fs::write(preset_path, serde_json::to_string_pretty(&active_preset).unwrap_or_default());

    let msg = if launched.is_empty() {
        "Preset launched (no models configured - configure models first).".to_string()
    } else {
        format!("Preset launched: {}", launched.join(", "))
    };

    info!("{}", msg);
    Json(serde_json::json!({"message": msg}))
}

async fn deactivate_preset() -> Json<serde_json::Value> {
    let preset_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/preset.json";
    let mut preset: serde_json::Value = match std::fs::read_to_string(preset_path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => serde_json::json!({"active": false}),
    };
    preset["active"] = serde_json::json!(false);
    let _ = std::fs::write(preset_path, serde_json::to_string_pretty(&preset).unwrap_or_default());
    info!("CESAROPS DEACTIVATED — freeform mode for coding/testing");
    Json(serde_json::json!({"message": "CESAROPS deactivated. Freeform mode."}))
}

async fn apply_freeform(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let freeform_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/freeform_state.json";
    match std::fs::write(freeform_path, serde_json::to_string_pretty(&body).unwrap_or_default()) {
        Ok(_) => {
            info!("Freeform config applied: coder={}, thinker={}, corrector={}, polisher={}",
                body.get("coder_model").and_then(|v| v.as_str()).unwrap_or("none"),
                body.get("thinker_model").and_then(|v| v.as_str()).unwrap_or("none"),
                body.get("corrector_model").and_then(|v| v.as_str()).unwrap_or("none"),
                body.get("polisher_model").and_then(|v| v.as_str()).unwrap_or("none"),
            );
            Json(serde_json::json!({"message": "Freeform configuration applied. Models loading."}))
        }
        Err(e) => Json(serde_json::json!({"error": format!("Failed to save freeform state: {}", e)})),
    }
}

async fn corrector_connect() -> Json<serde_json::Value> {
    match set_skip_corrector_config(false) {
        Ok(()) => {
            info!("Corrector CONNECTED");
            Json(serde_json::json!({"message": "Corrector connected. Will be used on next request."}))
        }
        Err(e) => Json(serde_json::json!({"error": format!("Failed to enable corrector: {}", e)})),
    }
}

async fn corrector_disconnect() -> Json<serde_json::Value> {
    match set_skip_corrector_config(true) {
        Ok(()) => {
            info!("Corrector DISCONNECTED");
            Json(serde_json::json!({"message": "Corrector disconnected. Qwen flies solo."}))
        }
        Err(e) => Json(serde_json::json!({"error": format!("Failed to disable corrector: {}", e)})),
    }
}

/// Send a task to any GPU endpoint in agent mode (with tools).
/// POST /cluster/agent/run { "endpoint": "http://...:5001", "message": "do something" }
async fn run_agent_task(
    State(state): State<AppState>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let endpoint = body.get("endpoint").and_then(|v| v.as_str()).unwrap_or("");
    let message = body.get("message").and_then(|v| v.as_str()).unwrap_or("");

    if endpoint.is_empty() || message.is_empty() {
        return Json(serde_json::json!({"error": "endpoint and message required"}));
    }

    let config = agent_dispatch::AgentConfig {
        endpoint_url: endpoint.to_string(),
        project_root: paths::project_root(),
        nautivecs_url: state.config.nautivecs_url.clone(),
        wso_url: state.config.wso_url.clone(),
        mcp_url: mcp_endpoint_from_config(),
        max_tokens: 12288,
        temperature: 0.4,
        safe_mode: body.get("safe_mode").and_then(|v| v.as_bool()).unwrap_or(false),
    };

    info!("Agent task dispatched to {}: {}...", endpoint, &message[..message.len().min(80)]);
    let result = agent_dispatch::run_agent_loop(&config, message).await;
    info!("Agent task complete: {}...", &result[..result.len().min(100)]);

    Json(serde_json::json!({"response": result}))
}

async fn get_routing_presets() -> Json<serde_json::Value> {
    let table = cluster_store::read_config();
    let presets = table
        .get("routing_preset")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| item.as_table())
                .map(|t| {
                    serde_json::json!({
                        "id": t.get("id").and_then(|v| v.as_str()).unwrap_or(""),
                        "name": t.get("name").and_then(|v| v.as_str()).unwrap_or(""),
                        "description": t.get("description").and_then(|v| v.as_str()).unwrap_or(""),
                        "chat_agent": t.get("chat_agent").and_then(|v| v.as_str()).unwrap_or(""),
                        "coder_endpoint": t.get("coder_endpoint").and_then(|v| v.as_str()).unwrap_or(""),
                        "reviewer_endpoint": t.get("reviewer_endpoint").and_then(|v| v.as_str()).unwrap_or(""),
                        "thinker_endpoint": t.get("thinker_endpoint").and_then(|v| v.as_str()).unwrap_or(""),
                        "corrector_endpoint": t.get("corrector_endpoint").and_then(|v| v.as_str()).unwrap_or(""),
                        "draft_endpoint": t.get("draft_endpoint").and_then(|v| v.as_str()).unwrap_or(""),
                        "fleet_node": t.get("fleet_node").and_then(|v| v.as_str()).unwrap_or(""),
                        "fleet_action": t.get("fleet_action").and_then(|v| v.as_str()).unwrap_or(""),
                        "workers_start": table_string_array(t, "workers_start"),
                        "workers_stop": table_string_array(t, "workers_stop"),
                    })
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Json(serde_json::json!({
        "presets": presets,
        "active_preset_id": routing::load_routing_state().active_preset_id,
    }))
}

async fn fleet_dispatch(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let node = body.get("node").and_then(|v| v.as_str()).unwrap_or("unknown");
    let action = body
        .get("action")
        .and_then(|v| v.as_str())
        .unwrap_or("sync_llm_endpoints");
    let table = cluster_store::read_config();
    let Some(url) = orchestration_url_for_action(&table, action) else {
        return Json(serde_json::json!({
            "error": "No n8n webhook configured in [orchestration]. Set n8n_fleet_url (and optionally n8n_pamp_url)."
        }));
    };

    let cargo_feedback = if action == "cargo_check_feedback" || action == "cargo_test_feedback" {
        let project_dir = resolve_project_dir(body.get("project_dir").and_then(|v| v.as_str()));
        Some(run_cargo_feedback(action, &project_dir))
    } else {
        None
    };

    let payload = serde_json::json!({
        "node": node,
        "action": action,
        "request": body,
        "cargo_feedback": cargo_feedback,
        "source": "forge-cluster-panel"
    });

    let client = reqwest::Client::new();
    match client.post(&url).json(&payload).send().await {
        Ok(resp) => {
            let status = resp.status().as_u16();
            let text = resp.text().await.unwrap_or_default();
            Json(serde_json::json!({
                "status": status,
                "message": format!("Dispatched '{}' for '{}' to n8n", action, node),
                "webhook": url,
                "response": text.chars().take(800).collect::<String>(),
            }))
        }
        Err(e) => Json(serde_json::json!({
            "error": format!("n8n dispatch failed: {}", e),
            "webhook": url
        })),
    }
}

async fn apply_routing_preset(
    Path(preset_id): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let start_workers = body
        .get("start_workers")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let table = cluster_store::read_config();
    let Some(preset) = find_routing_preset(&table, &preset_id) else {
        return Json(serde_json::json!({"error": format!("routing preset '{}' not found", preset_id)}));
    };

    let mut state = routing::load_routing_state();
    state.chat_agent = preset
        .get("chat_agent")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.coder_endpoint = preset
        .get("coder_endpoint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.reviewer_endpoint = preset
        .get("reviewer_endpoint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.thinker_endpoint = preset
        .get("thinker_endpoint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.corrector_endpoint = preset
        .get("corrector_endpoint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.draft_endpoint = preset
        .get("draft_endpoint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    state.active_preset_id = preset_id.clone();
    routing::save_routing_state(&state);

    let workers_start = table_string_array(&preset, "workers_start");
    let workers_stop = table_string_array(&preset, "workers_stop");
    let mut started = Vec::new();
    let mut failed = Vec::new();

    if start_workers {
        let client = reqwest::Client::new();
        for name in &workers_stop {
            let url = format!("http://127.0.0.1:9100/cluster/worker/{}/stop", name);
            match client.post(&url).json(&serde_json::json!({})).send().await {
                Ok(_) => {}
                Err(e) => failed.push(format!("stop {}: {}", name, e)),
            }
        }
        for name in &workers_start {
            let url = format!("http://127.0.0.1:9100/cluster/worker/{}/start", name);
            match client.post(&url).json(&serde_json::json!({})).send().await {
                Ok(_) => started.push(name.clone()),
                Err(e) => failed.push(format!("start {}: {}", name, e)),
            }
        }
    }

    // Optional n8n fleet hook from preset metadata.
    let fleet_node = preset
        .get("fleet_node")
        .and_then(|v| v.as_str())
        .unwrap_or("cesarops2");
    let fleet_action = preset
        .get("fleet_action")
        .and_then(|v| v.as_str())
        .unwrap_or("sync_llm_endpoints");
    let mut dispatch = serde_json::Value::Null;
    if let Some(url) = orchestration_url_for_action(&table, fleet_action) {
        let payload = serde_json::json!({
            "node": fleet_node,
            "action": fleet_action,
            "preset_id": preset_id,
            "source": "forge-routing-preset"
        });
        let client = reqwest::Client::new();
        dispatch = match client.post(&url).json(&payload).send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                let text = resp.text().await.unwrap_or_default();
                serde_json::json!({
                    "ok": (200..300).contains(&status),
                    "status": status,
                    "webhook": url,
                    "body": text.chars().take(800).collect::<String>(),
                })
            }
            Err(e) => serde_json::json!({"ok": false, "error": e.to_string(), "webhook": url}),
        };
    }

    Json(serde_json::json!({
        "message": format!("Applied routing preset '{}'", preset_id),
        "started": started,
        "failed": failed,
        "dispatch": dispatch
    }))
}

// --- Cluster Control API ---

async fn list_lanes() -> Json<serde_json::Value> {
    Json(stream_lanes::list_lanes_json())
}

async fn lanes_activity(State(state): State<AppState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "activity": state.lanes.snapshot().await,
        "netdata_url": routing::netdata_url(),
    }))
}

async fn set_lane_role(
    Path(lane_id): Path<String>,
    Json(body): Json<LaneRoleRequest>,
) -> Json<serde_json::Value> {
    routing::set_lane_role(&lane_id, &body.role);
    Json(serde_json::json!({
        "message": format!("{} → role {}", lane_id, body.role),
        "endpoint": routing::resolve_lane_coder_url(&lane_id),
    }))
}

async fn get_roles() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "roles": routing::load_role_endpoints(),
        "catalog": routing::LANE_ROLE_CATALOG,
    }))
}

async fn get_gpu_fleet() -> Json<serde_json::Value> {
    Json(cluster_store::gpu_fleet_json())
}

async fn apply_gpu(
    Path(gpu_id): Path<i64>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let role = body.get("role").and_then(|v| v.as_str()).unwrap_or("idle");
    let model = body.get("model").and_then(|v| v.as_str()).unwrap_or("");
    let engine = body.get("engine").and_then(|v| v.as_str()).unwrap_or("llama-server");
    let backend = body.get("backend").and_then(|v| v.as_str()).unwrap_or("cuda");
    match cluster_store::apply_gpu_binding(gpu_id, role, model, engine, backend) {
        Ok(msg) => Json(serde_json::json!({"message": msg})),
        Err(e) => Json(serde_json::json!({"error": e})),
    }
}

/// Collect distinct remote hosts (with ssh creds) referenced by [[worker]] rows.
/// Returns (host, ssh_user, ssh_port) tuples, deduplicated by host.
fn remote_worker_hosts() -> Vec<(String, String, i64)> {
    let table = cluster_store::read_config();
    let mut seen = std::collections::HashSet::new();
    let mut hosts = Vec::new();

    let Some(workers) = table.get("worker").and_then(|v| v.as_array()) else {
        return hosts;
    };
    for w in workers {
        let Some(row) = w.as_table() else { continue };
        let host = row.get("host").and_then(|v| v.as_str()).unwrap_or("local");
        let is_local = host == "local" || host == "127.0.0.1" || host == "localhost";
        if is_local || !seen.insert(host.to_string()) {
            continue;
        }
        let ssh_user = row
            .get("ssh_user")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("cesarops")
            .to_string();
        let ssh_port = row.get("ssh_port").and_then(|v| v.as_integer()).unwrap_or(22);
        hosts.push((host.to_string(), ssh_user, ssh_port));
    }
    hosts
}

const KILL_ALL_ENGINES_CMD: &str =
    "pkill -f 'cesarops-inference.*--backend' ; pkill -f 'llama-server.*--port' ; pkill -f 'koboldcpp.*--model' ; true";

/// Run the kill-all command locally and on every distinct remote host referenced
/// by [[worker]] entries. Returns (host, ok) results for remote attempts.
async fn kill_all_engines_everywhere() -> Vec<(String, bool)> {
    let _ = std::process::Command::new("bash")
        .arg("-c")
        .arg(KILL_ALL_ENGINES_CMD)
        .output();

    let hosts = remote_worker_hosts();
    let mut results = Vec::new();
    for (host, ssh_user, ssh_port) in hosts {
        let ok = std::process::Command::new("ssh")
            .arg("-o")
            .arg("BatchMode=yes")
            .arg("-o")
            .arg("ConnectTimeout=5")
            .arg("-p")
            .arg(ssh_port.to_string())
            .arg(format!("{}@{}", ssh_user, host))
            .arg("bash")
            .arg("-lc")
            .arg(KILL_ALL_ENGINES_CMD)
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if !ok {
            warn!("Remote kill-all may have failed on {}", host);
        }
        results.push((host, ok));
    }
    results
}

async fn fleet_clear_all() -> Json<serde_json::Value> {
    let remote_results = kill_all_engines_everywhere().await;
    match cluster_store::clear_all_fleet_bindings() {
        Ok(n) => Json(serde_json::json!({
            "message": format!(
                "Stopped local + {} remote host(s), cleared {} worker bindings to idle",
                remote_results.len(), n
            ),
            "remote_hosts": remote_results.iter().map(|(h, ok)| serde_json::json!({"host": h, "ssh_ok": ok})).collect::<Vec<_>>(),
        })),
        Err(e) => Json(serde_json::json!({"error": e})),
    }
}

async fn launch_candle_big(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let gpu = body.get("gpu_id").and_then(|v| v.as_i64()).unwrap_or(0);
    let port = body.get("port").and_then(|v| v.as_i64()).unwrap_or(5012);
    let model = body
        .get("model")
        .and_then(|v| v.as_str())
        .unwrap_or("/data/cesarops/local_models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf");

    if gpu > 1 {
        return Json(serde_json::json!({
            "error": "Candle/native inference only runs on T440 (GPU 0 or 1). Remote nodes use llama-server via cesarops2 lab script."
        }));
    }

    let bin = "/codebase/repos/wreckhunter2000-1/cesarops-inference/target/release/cesarops-inference";
    if !std::path::Path::new(bin).exists() {
        return Json(serde_json::json!({
            "error": format!("cesarops-inference binary not found at {} — run cargo build -p cesarops-inference --release", bin)
        }));
    }

    let _ = std::process::Command::new("bash")
        .arg("-c")
        .arg(format!("fuser -k {}/tcp 2>/dev/null; true", port))
        .output();

    let cmd = format!(
        "nohup {} --model {} --port {} --backend wgpu --gpu {} > /tmp/candle_gpu{}.log 2>&1 &",
        bin, model, port, gpu, gpu
    );
    match std::process::Command::new("bash").arg("-c").arg(&cmd).output() {
        Ok(_) => Json(serde_json::json!({
            "message": format!("Candle/wgpu loading {} on GPU {} port {}", model.split('/').last().unwrap_or(model), gpu, port),
            "endpoint": format!("http://127.0.0.1:{}", port),
        })),
        Err(e) => Json(serde_json::json!({"error": format!("Launch failed: {}", e)})),
    }
}

async fn worker_status(Path(name): Path<String>) -> Json<serde_json::Value> {
    let Some((_, row)) = cluster_store::worker_row(&name) else {
        return Json(serde_json::json!({"error": "worker not found"}));
    };
    let host = row.get("host").and_then(|v| v.as_str()).unwrap_or("local");
    let port = row.get("port").and_then(|v| v.as_integer()).unwrap_or(5001);
    let ip = if host == "local" {
        "127.0.0.1".to_string()
    } else {
        host.to_string()
    };
    let url = format!("http://{}:{}", ip, port);
    Json(cluster_store::probe_endpoint(&url).await)
}

async fn get_cluster_config() -> Json<serde_json::Value> {
    let config_path = paths::cluster_config_path();
    match std::fs::read_to_string(config_path) {
        Ok(content) => {
            match content.parse::<toml::Table>() {
                Ok(table) => {
                    // Convert TOML to JSON for the frontend
                    let mut result = serde_json::json!({});
                    
                    // Bootstrap section
                    if let Some(bootstrap) = table.get("bootstrap") {
                        result["bootstrap"] = toml_to_json(bootstrap);
                    }
                    
                    // GPUs
                    if let Some(gpus) = table.get("gpu").and_then(|v| v.as_array()) {
                        result["gpus"] = serde_json::Value::Array(
                            gpus.iter().map(|g| toml_to_json(g)).collect()
                        );
                    }
                    
                    // Workers
                    if let Some(workers) = table.get("worker").and_then(|v| v.as_array()) {
                        result["workers"] = serde_json::Value::Array(
                            workers.iter().map(|w| toml_to_json(w)).collect()
                        );
                    }
                    
                    Json(result)
                }
                Err(e) => Json(serde_json::json!({"error": format!("TOML parse error: {}", e)})),
            }
        }
        Err(e) => Json(serde_json::json!({"error": format!("Config not found: {}", e)})),
    }
}

async fn save_cluster_config(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let config_path = paths::cluster_config_path();
    
    // Rebuild TOML from the JSON config
    let mut toml_str = String::from("# Cluster Configuration — managed by web UI\n\n");
    
    if let Some(bootstrap) = body.get("bootstrap") {
        toml_str.push_str("[bootstrap]\n");
        if let Some(m) = bootstrap.get("model").and_then(|v| v.as_str()) {
            toml_str.push_str(&format!("model = \"{}\"\n", m));
        }
        if let Some(p) = bootstrap.get("port").and_then(|v| v.as_u64()) {
            toml_str.push_str(&format!("port = {}\n", p));
        }
        toml_str.push_str("backend = \"cpu\"\n");
        if let Some(t) = bootstrap.get("template").and_then(|v| v.as_str()) {
            toml_str.push_str(&format!("template = \"{}\"\n", t));
        }
        toml_str.push('\n');
    }
    
    if let Some(gpus) = body.get("gpus").and_then(|v| v.as_array()) {
        for gpu in gpus {
            toml_str.push_str("[[gpu]]\n");
            if let Some(id) = gpu.get("id").and_then(|v| v.as_u64()) {
                toml_str.push_str(&format!("id = {}\n", id));
            }
            if let Some(name) = gpu.get("name").and_then(|v| v.as_str()) {
                toml_str.push_str(&format!("name = \"{}\"\n", name));
            }
            if let Some(vram) = gpu.get("vram_mb").and_then(|v| v.as_u64()) {
                toml_str.push_str(&format!("vram_mb = {}\n", vram));
            }
            toml_str.push('\n');
        }
    }
    
    if let Some(workers) = body.get("workers").and_then(|v| v.as_array()) {
        for w in workers {
            toml_str.push_str("[[worker]]\n");
            if let Some(n) = w.get("name").and_then(|v| v.as_str()) {
                toml_str.push_str(&format!("name = \"{}\"\n", n));
            }
            if let Some(r) = w.get("role").and_then(|v| v.as_str()) {
                toml_str.push_str(&format!("role = \"{}\"\n", r));
            }
            if let Some(g) = w.get("gpu").and_then(|v| v.as_u64()) {
                toml_str.push_str(&format!("gpu = {}\n", g));
            }
            if let Some(m) = w.get("model").and_then(|v| v.as_str()) {
                toml_str.push_str(&format!("model = \"{}\"\n", m));
            }
            if let Some(p) = w.get("port").and_then(|v| v.as_u64()) {
                toml_str.push_str(&format!("port = {}\n", p));
            }
            if let Some(t) = w.get("template").and_then(|v| v.as_str()) {
                toml_str.push_str(&format!("template = \"{}\"\n", t));
            }
            let enabled = w.get("enabled").and_then(|v| v.as_bool()).unwrap_or(false);
            toml_str.push_str(&format!("enabled = {}\n\n", enabled));
        }
    }
    
    match std::fs::write(config_path, &toml_str) {
        Ok(_) => Json(serde_json::json!({"message": "Config saved successfully."})),
        Err(e) => Json(serde_json::json!({"error": format!("Failed to write config: {}", e)})),
    }
}

async fn list_available_models() -> Json<serde_json::Value> {
    let models_dir = paths::models_dir();
    let mut models: Vec<String> = Vec::new();
    
    if let Ok(entries) = std::fs::read_dir(models_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if let Some(ext) = path.extension() {
                if ext == "gguf" {
                    models.push(path.to_string_lossy().to_string());
                }
            }
        }
    }
    models.sort();
    Json(serde_json::json!(models))
}


fn estimate_model_requirements(path: &str) -> (u32, &'static str, &'static str) {
    let filename = path.split('/').last().unwrap_or(path).to_lowercase();
    let is_moe = filename.contains("moe") || filename.contains("a3b");
    let is_phi = filename.contains("phi");
    let is_tiny = filename.contains("tiny") || filename.contains("1.1b");
    let is_7b = filename.contains("7b");
    let is_9b = filename.contains("9b");
    let is_14b = filename.contains("14b");
    let is_22b = filename.contains("22b");
    let is_26b = filename.contains("26b");
    let is_32b = filename.contains("32b");
    let is_35b = filename.contains("35b");

    let q_mult = if filename.contains("q4_k_m") { 0.28 }
        else if filename.contains("q4_0") { 0.25 }
        else if filename.contains("q6_k") { 0.38 }
        else if filename.contains("q8_0") { 0.50 }
        else if filename.contains("f16") || filename.contains("fp16") { 1.0 }
        else { 0.30 };

    let base_params_b = if is_tiny { 1.1 }
        else if is_phi { 3.8 }
        else if is_7b { 7.0 }
        else if is_9b { 9.0 }
        else if is_14b { 14.0 }
        else if is_22b { 22.0 }
        else if is_26b { 26.0 }
        else if is_32b { 32.0 }
        else if is_35b { 35.0 }
        else { 7.0 };

    let total_params_b = if is_moe && filename.contains("a3b") { 3.0 } else { base_params_b };
    let vram_fp16 = (total_params_b * 2.0) as u32;
    let vram_needed = ((vram_fp16 as f32) * q_mult + 2048.0).max(1024.0) as u32;

    let role = if is_tiny { "validator" }
        else if filename.contains("coder") && filename.contains("14b") { "coder" }
        else if filename.contains("coder") && is_7b { "thinker" }
        else if is_moe && is_35b { "coder" }
        else if filename.contains("r1") || filename.contains("think") { "thinker" }
        else if is_phi { "fleet_command" }
        else { "general" };

    (vram_needed, role, "auto-fit estimate")
}

fn parse_csv_i64(input: &str) -> Vec<i64> {
    input
        .split(',')
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .filter_map(|s| s.parse::<i64>().ok())
        .collect()
}

fn parse_csv_strings(input: &str) -> Vec<String> {
    input
        .split(',')
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect()
}

async fn model_fit_recommendations(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let gpu_ids: Vec<i64> = body.get("gpu_ids").and_then(|v| v.as_array()).map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect()).unwrap_or_default();

    let table = cluster_store::read_config();
    let gpus = table.get("gpu").and_then(|v| v.as_array()).cloned().unwrap_or_default();

    let mut selected: Vec<serde_json::Value> = Vec::new();
    let mut total_vram: u32 = 0;
    for g in &gpus {
        let gt = match g.as_table() { Some(t) => t, None => continue };
        let id = gt.get("id").and_then(|v| v.as_integer()).unwrap_or(-1);
        if gpu_ids.contains(&id) {
            let vram = gt.get("vram_mb").and_then(|v| v.as_integer()).unwrap_or(0) as u32;
            total_vram += vram;
            selected.push(serde_json::json!({"id": id, "name": gt.get("name").and_then(|v| v.as_str()).unwrap_or("?"), "vram_mb": vram, "host": gt.get("host").and_then(|v| v.as_str()).unwrap_or("local")}));
        }
    }

    let all_models = match list_available_models().await.0 { m => m.as_array().cloned().unwrap_or_default() };
    let mut fitting: Vec<serde_json::Value> = Vec::new();
    let mut too_big: Vec<serde_json::Value> = Vec::new();

    for m in &all_models {
        let path = m.as_str().unwrap_or("");
        let (vram_needed, role, notes) = estimate_model_requirements(path);
        if vram_needed <= total_vram {
            fitting.push(serde_json::json!({"path": path, "vram_needed_mb": vram_needed, "recommended_role": role, "notes": notes}));
        } else {
            too_big.push(serde_json::json!({"path": path, "vram_needed_mb": vram_needed, "notes": "exceeds selected VRAM"}));
        }
    }

    fitting.sort_by(|a, b| { let va = a.get("vram_needed_mb").and_then(|v| v.as_u64()).unwrap_or(0); let vb = b.get("vram_needed_mb").and_then(|v| v.as_u64()).unwrap_or(0); vb.cmp(&va) });

    let suggested_roles: Vec<serde_json::Value> = selected.iter().map(|g| {
        let id = g.get("id").and_then(|v| v.as_i64()).unwrap_or(0);
        let vram = g.get("vram_mb").and_then(|v| v.as_u64()).unwrap_or(0);
        let role = if id == 5 { "fleet_command" } else if vram >= 16384 { "coder" } else if vram >= 8192 { "thinker" } else if vram >= 4096 { "reviewer" } else { "validator" };
        serde_json::json!({"gpu_id": id, "suggested_role": role})
    }).collect();

    Json(serde_json::json!({
        "selected_gpus": selected,
        "total_vram_mb": total_vram,
        "models_that_fit": fitting,
        "models_too_big": too_big,
        "suggested_roles": suggested_roles,
        "available_servers": ["llama-server (CUDA / Vulkan)", "koboldcpp (Vulkan fallback)", "cesarops-inference (native wgpu)"],
    }))
}


async fn start_worker(Path(path): Path<String>) -> Json<serde_json::Value> {
    let table = cluster_store::read_config();
    let workers_arr = table
        .get("worker")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let idx = match cluster_store::resolve_worker_idx(&workers_arr, &path) {
        Some(i) => i,
        None => return Json(serde_json::json!({"error": format!("Worker not found: {}", path)})),
    };

    let workers = table.get("worker").and_then(|v| v.as_array());
    let Some(worker) = workers.and_then(|w| w.get(idx)) else {
        return Json(serde_json::json!({"error": "Worker index out of range"}));
    };

    let model = worker.get("model").and_then(|v| v.as_str()).unwrap_or("");
    let port = worker.get("port").and_then(|v| v.as_integer()).unwrap_or(5010);
    let gpu = worker.get("gpu").and_then(|v| v.as_integer()).unwrap_or(0);
    let name = worker.get("name").and_then(|v| v.as_str()).unwrap_or("worker");
    let host = worker.get("host").and_then(|v| v.as_str()).unwrap_or("local");
    let is_local_host = host == "local" || host == "127.0.0.1" || host == "localhost";
    let ssh_user = worker
        .get("ssh_user")
        .and_then(|v| v.as_str())
        .unwrap_or("cesarops");
    let ssh_port = worker.get("ssh_port").and_then(|v| v.as_integer()).unwrap_or(22);
    let engine_pin = worker.get("engine").and_then(|v| v.as_str()).unwrap_or("llama-server");
    let backend = worker.get("backend").and_then(|v| v.as_str()).unwrap_or("cuda");
    let vulkan_device = worker
        .get("vulkan_device")
        .and_then(|v| v.as_integer())
        .unwrap_or(gpu);
    let gpu_ids = parse_csv_i64(
        worker
            .get("gpu_ids")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    );
    let tensor_split = parse_csv_strings(
        worker
            .get("tensor_split")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    );
    let gpulayers = worker.get("gpulayers").and_then(|v| v.as_integer()).unwrap_or(99);
    let contextsize = worker.get("contextsize").and_then(|v| v.as_integer()).unwrap_or(8192);
    let threads = worker.get("threads").and_then(|v| v.as_integer()).unwrap_or(4);

    if model.is_empty() {
        return Json(serde_json::json!({"error": "No model assigned. Pick a model in GPU Fleet and APPLY."}));
    }
    let native_quants = ["q4_0", "q4_k_m", "q6_k", "q8_0", "f16", "f32", "bf16"];
    let model_lower = model.to_lowercase();
    let use_native = match engine_pin {
        "cesarops-inference" | "native" | "wgpu" => true,
        "koboldcpp" | "llama-server" | "llama.cpp" => false,
        _ => native_quants.iter().any(|q| model_lower.contains(q)),
    };
    if !is_local_host && use_native {
        return Json(serde_json::json!({
            "error": format!("Worker {} uses native engine on remote host {}. Switch to llama-server or koboldcpp.", name, host)
        }));
    }
    let effective = inference_client::effective_worker_engine(engine_pin, use_native);

    let cmd = if use_native {
        format!(
            "nohup /codebase/repos/wreckhunter2000-1/cesarops-inference/target/release/cesarops-inference \
             --model {} --port {} --backend wgpu --gpu {} > /tmp/worker_{}.log 2>&1 &",
            model, port, gpu, idx
        )
    } else if effective == "koboldcpp" {
        let tensor_split_arg = if tensor_split.is_empty() {
            String::new()
        } else {
            format!(" --tensor_split {}", tensor_split.join(","))
        };
        format!(
            "setsid /home/cesarops/koboldcpp --model {} --port {} --usevulkan {} --gpulayers {} \
             --contextsize {} --threads {}{} --quiet > /tmp/worker_{}.log 2>&1 < /dev/null & disown",
            model, port, vulkan_device, gpulayers, contextsize, threads, tensor_split_arg, idx
        )
    } else {
        inference_client::llama_server_spawn_cmd(
            model,
            port,
            backend,
            gpulayers,
            contextsize,
            threads,
            &tensor_split,
            &gpu_ids,
            idx,
        )
    };

    let launch_result = if is_local_host {
        std::process::Command::new("bash").arg("-c").arg(&cmd).output()
    } else {
        std::process::Command::new("ssh")
            .arg("-o")
            .arg("BatchMode=yes")
            .arg("-o")
            .arg("ConnectTimeout=4")
            .arg("-p")
            .arg(ssh_port.to_string())
            .arg(format!("{}@{}", ssh_user, host))
            .arg("bash")
            .arg("-lc")
            .arg(&cmd)
            .output()
    };

    match launch_result {
        Ok(_) => Json(serde_json::json!({
            "message": format!(
                "Started {} on {}:{} via {}{}",
                name,
                if is_local_host { "127.0.0.1" } else { host },
                port,
                effective,
                if gpu_ids.is_empty() {
                    format!(" (gpu={})", gpu)
                } else {
                    format!(" (gpu_ids={})", gpu_ids.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(","))
                }
            ),
            "endpoint": format!("http://{}:{}", if is_local_host { "127.0.0.1" } else { host }, port),
        })),
        Err(e) => Json(serde_json::json!({"error": format!("Failed to start: {}", e)})),
    }
}

async fn stop_worker(Path(path): Path<String>) -> Json<serde_json::Value> {
    let table = cluster_store::read_config();
    let workers_arr = table
        .get("worker")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let idx = match cluster_store::resolve_worker_idx(&workers_arr, &path) {
        Some(i) => i,
        None => return Json(serde_json::json!({"error": format!("Worker not found: {}", path)})),
    };
    let workers = table.get("worker").and_then(|v| v.as_array());
    let Some(worker) = workers.and_then(|w| w.get(idx)) else {
        return Json(serde_json::json!({"error": "Worker not found"}));
    };
    let port = worker.get("port").and_then(|v| v.as_integer()).unwrap_or(5010);
    let name = worker.get("name").and_then(|v| v.as_str()).unwrap_or("worker");
    let cmd = format!(
        "fuser -k {}/tcp 2>/dev/null; pkill -f 'llama-server.*--port {}' 2>/dev/null; \
         pkill -f 'koboldcpp.*--port {}' 2>/dev/null; true",
        port, port, port
    );
    let _ = std::process::Command::new("bash").arg("-c").arg(&cmd).output();
    Json(serde_json::json!({"message": format!("Stopped {} (port {})", name, port)}))
}

async fn start_all_workers() -> Json<serde_json::Value> {
    // TODO: iterate workers and start each
    Json(serde_json::json!({"message": "Starting all workers... (use individual start for now)"}))
}

async fn stop_all_workers() -> Json<serde_json::Value> {
    let _ = std::process::Command::new("bash")
        .arg("-c")
        .arg("pkill -f 'cesarops-inference.*--backend wgpu'")
        .output();
    Json(serde_json::json!({"message": "All GPU workers stopped."}))
}

/// Discover which nodes are online by probing Tailscale status + known service ports
async fn discover_nodes() -> Json<serde_json::Value> {
    let config_path = paths::cluster_config_path();
    let content = std::fs::read_to_string(config_path).unwrap_or_default();
    let table: toml::Table = content.parse().unwrap_or_default();

    // First, get live Tailscale peer status
    let tailscale_peers = get_tailscale_peers().await;

    let mut results = Vec::new();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .unwrap();

    if let Some(nodes) = table.get("known_nodes").and_then(|v| v.as_array()) {
        for node in nodes {
            let name = node.get("name").and_then(|v| v.as_str()).unwrap_or("unknown");
            let ip = node.get("ip").and_then(|v| v.as_str()).unwrap_or("");
            let gpu_label = node.get("gpu").and_then(|v| v.as_str()).unwrap_or("");
            let alt_ip = node.get("alt_ip").and_then(|v| v.as_str()).unwrap_or("");
            let empty_ports = vec![];
            let ports = node.get("ports").and_then(|v| v.as_array()).unwrap_or(&empty_ports);

            // Check if Tailscale sees this peer as online
            let ts_online = if ip == "127.0.0.1" {
                true // local is always online
            } else {
                tailscale_peers.iter().any(|p| p.0 == ip && p.1)
            };

            let mut probe_hosts: Vec<&str> = vec![ip];
            if !alt_ip.is_empty() && alt_ip != ip {
                probe_hosts.push(alt_ip);
            }

            let mut port_status = Vec::new();
            for port_val in ports {
                let port = port_val.as_integer().unwrap_or(0);
                let mut reachable = false;
                let mut info = serde_json::Value::Null;
                let mut status_code = serde_json::Value::Null;
                let mut probed_host = serde_json::Value::Null;
                let mut last_error: Option<String> = None;

                for host in &probe_hosts {
                    let url = format!("http://{}:{}/health", host, port);
                    match client.get(&url).send().await {
                        Ok(resp) => {
                            reachable = true;
                            status_code = serde_json::json!(resp.status().as_u16());
                            probed_host = serde_json::json!(host);

                            let code = resp.status();
                            if code.is_success() {
                                let body_text = resp.text().await.unwrap_or_default();
                                info = serde_json::from_str(&body_text).unwrap_or(serde_json::json!({
                                    "status_code": code.as_u16(),
                                    "body": body_text.chars().take(240).collect::<String>(),
                                }));
                            } else {
                                let body_text = resp.text().await.unwrap_or_default();
                                info = serde_json::json!({
                                    "status_code": code.as_u16(),
                                    "body": body_text.chars().take(240).collect::<String>(),
                                });
                            }
                            break;
                        }
                        Err(e) => {
                            last_error = Some(e.to_string());
                        }
                    }
                }

                if !reachable {
                    if let Some(err) = last_error {
                        info = serde_json::json!({ "error": err });
                    }
                }

                port_status.push(serde_json::json!({
                    "port": port,
                    "online": reachable,
                    "status_code": status_code,
                    "probed_host": probed_host,
                    "info": info,
                }));
            }
            // Dynamic GPU Probe
            let mut gpus = Vec::new();
            if ts_online {
                use tokio::process::Command;
                use tokio::time::{timeout, Duration};
                let probe_result = if ip == "127.0.0.1" || ip == "localhost" {
                    timeout(Duration::from_secs(2), Command::new("nvidia-smi")
                        .args(&["--query-gpu=name,temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total", "--format=csv,noheader"])
                        .output())
                    .await
                } else {
                    timeout(Duration::from_secs(3), Command::new("ssh")
                        .args(&[
                            "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=2",
                            &format!("cesarops@{}", ip),
                            "nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total", "--format=csv,noheader"
                        ])
                        .output())
                    .await
                };
                
                if let Ok(Ok(output)) = probe_result {
                    if output.status.success() {
                        let stdout = String::from_utf8_lossy(&output.stdout);
                        for line in stdout.lines() {
                            let l = line.trim();
                            if !l.is_empty() {
                                let parts: Vec<&str> = l.split(',').map(|s| s.trim()).collect();
                                if parts.len() >= 6 {
                                    let name = parts[0].to_string();
                                    let temp: f64 = parts[1].parse().unwrap_or(0.0);
                                    let util: f64 = parts[2].trim_end_matches(" %").parse().unwrap_or(0.0);
                                    let power: f64 = parts[3].trim_end_matches(" W").parse().unwrap_or(0.0);
                                    let mem_used: f64 = parts[4].trim_end_matches(" MiB").parse().unwrap_or(0.0);
                                    let mem_total: f64 = parts[5].trim_end_matches(" MiB").parse().unwrap_or(0.0);
                                    gpus.push(serde_json::json!({
                                        "name": name,
                                        "temp_c": temp,
                                        "temp_f": (temp * 9.0 / 5.0) + 32.0,
                                        "util_pct": util,
                                        "power_w": power,
                                        "mem_used_mb": mem_used,
                                        "mem_total_mb": mem_total
                                    }));
                                }
                            }
                        }
                    }
                }
            }

            let any_service_online = port_status.iter().any(|p| p.get("online").and_then(|v| v.as_bool()).unwrap_or(false));
            results.push(serde_json::json!({
                "name": name,
                "ip": ip,
                "gpus": gpus,
                "gpu": gpu_label,
                "ports": port_status,
                "online": ts_online || any_service_online,
            }));
        }
    }

    Json(serde_json::Value::Array(results))
}

async fn get_scores() -> Json<serde_json::Value> {
    // Static scores requested by user, including nemotron
    Json(serde_json::json!({
        "Qwen3.6-35B-A3B-MTP": 85,
        "Nemotron-Ultra-4B": 95,
        "TinyLlama-1.1B": 70,
        "Gemma-4-31B": 88
    }))
}

async fn wall_dashboard() -> impl axum::response::IntoResponse {
    let path = "/home/cesarops/cesarops_push/forge_src/wall.html";
    match std::fs::read_to_string(path) {
        Ok(html) => axum::response::Html(html),
        Err(_) => axum::response::Html("<h1>Wall Not Found</h1><p>Please create wall.html</p>".to_string()),
    }
}

/// Parse `tailscale status` to get peer online/offline state
async fn get_tailscale_peers() -> Vec<(String, bool)> {
    let output = match tokio::process::Command::new("tailscale")
        .args(["status", "--json"])
        .output()
        .await
    {
        Ok(o) => o,
        Err(_) => return Vec::new(),
    };

    if !output.status.success() {
        return Vec::new();
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let val: serde_json::Value = match serde_json::from_str(&json_str) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    let mut peers = Vec::new();

    // Self is always online
    if let Some(self_node) = val.get("Self") {
        if let Some(addrs) = self_node.get("TailscaleIPs").and_then(|v| v.as_array()) {
            for addr in addrs {
                if let Some(ip) = addr.as_str() {
                    peers.push((ip.to_string(), true));
                }
            }
        }
    }

    // Peers
    if let Some(peer_map) = val.get("Peer").and_then(|v| v.as_object()) {
        for (_key, peer) in peer_map {
            let online = peer.get("Online").and_then(|v| v.as_bool()).unwrap_or(false);
            if let Some(addrs) = peer.get("TailscaleIPs").and_then(|v| v.as_array()) {
                for addr in addrs {
                    if let Some(ip) = addr.as_str() {
                        peers.push((ip.to_string(), online));
                    }
                }
            }
        }
    }

    peers
}

/// Helper: convert a TOML value to serde_json::Value
fn toml_to_json(val: &toml::Value) -> serde_json::Value {
    match val {
        toml::Value::String(s) => serde_json::json!(s),
        toml::Value::Integer(i) => serde_json::json!(i),
        toml::Value::Float(f) => serde_json::json!(f),
        toml::Value::Boolean(b) => serde_json::json!(b),
        toml::Value::Array(arr) => serde_json::Value::Array(arr.iter().map(toml_to_json).collect()),
        toml::Value::Table(t) => {
            let mut map = serde_json::Map::new();
            for (k, v) in t {
                map.insert(k.clone(), toml_to_json(v));
            }
            serde_json::Value::Object(map)
        }
        _ => serde_json::Value::Null,
    }
}

// ── Per-card cluster control handlers ───────────────────────────────────────

/// POST /cluster/worker/{name}/apply — apply all settings for one worker
async fn worker_apply(
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    info!("Worker apply: {}", name);
    match cluster_store::update_worker_config(&name, &body) {
        Ok(()) => Json(serde_json::json!({"message": format!("Worker {} saved to cluster config", name)})),
        Err(e) => Json(serde_json::json!({"error": e})),
    }
}

/// POST /cluster/worker/{name}/set_injection { "enabled": bool }
async fn worker_set_injection(
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let enabled = body.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true);
    match cluster_store::update_worker_field(&name, "inject_vectors", serde_json::json!(enabled)) {
        Ok(()) => Json(serde_json::json!({"message": format!("{} injection={}", name, enabled)})),
        Err(e) => Json(serde_json::json!({"error": e})),
    }
}

async fn worker_set_backend(
    Path(name): Path<String>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let backend = body.get("backend").and_then(|v| v.as_str()).unwrap_or("vulkan");
    match cluster_store::update_worker_field(&name, "backend", serde_json::json!(backend)) {
        Ok(()) => Json(serde_json::json!({"message": format!("{} backend={}", name, backend)})),
        Err(e) => Json(serde_json::json!({"error": e})),
    }
}

/// POST /cluster/corrector/set_function { "function": "json_fixer", "enabled": bool }
async fn corrector_set_function(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let func = body.get("function").and_then(|v| v.as_str()).unwrap_or("");
    let enabled = body.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true);
    info!("Corrector function {} → {}", func, enabled);
    // Persist to cluster_config.toml corrector_functions table
    update_corrector_function(func, enabled);
    Json(serde_json::json!({"message": format!("corrector.{} = {}", func, enabled)}))
}

/// GET /cluster/engines — probe what inference engines are installed
async fn get_available_engines() -> Json<serde_json::Value> {
    let mut available: Vec<&str> = Vec::new();

    // Check local binaries
    if std::path::Path::new("/usr/bin/koboldcpp").exists()
        || std::path::Path::new("/home/cesarops/koboldcpp").exists()
        || std::path::Path::new("/home/cesarops/benchmark/koboldcpp").exists() {
        available.push("koboldcpp");
    }
    if std::path::Path::new("/home/cesarops/wreckhunter2000-1/cesarops-inference/target/release/cesarops-inference").exists() {
        available.push("cesarops-inference");
    }
    // Check ollama
    if reqwest::Client::new()
        .get("http://localhost:11434/api/tags")
        .timeout(std::time::Duration::from_secs(1))
        .send().await.map(|r| r.status().is_success()).unwrap_or(false) {
        available.push("ollama");
    }

    // Per-node: remote nodes only have koboldcpp (we know this from our setup)
    let per_node = serde_json::json!({
        "127.0.0.1":       available,
        "100.102.158.111": ["koboldcpp"],
        "100.105.77.74":   ["koboldcpp"],
        "100.110.214.86":  ["koboldcpp"],
    });

    Json(serde_json::json!({ "available": available, "per_node": per_node }))
}

/// POST /cluster/memory_pool/create { "name": "pool1", "members": ["Coder","Thinker"] }
async fn memory_pool_create(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let name = body.get("name").and_then(|v| v.as_str()).unwrap_or("pool1");
    let members: Vec<String> = body.get("members")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    info!("Memory pool created: {} members={:?}", name, members);
    // Persist pool to cluster_config.toml
    Json(serde_json::json!({"message": format!("Pool '{}' created with {} members", name, members.len())}))
}

async fn get_cluster_config_full() -> Json<serde_json::Value> {
    Json(cluster_store::full_panel_config())
}

fn update_corrector_function(func: &str, enabled: bool) {
    let mut table = cluster_store::read_config();
    let Some(workers) = table.get_mut("worker").and_then(|v| v.as_array_mut()) else {
        warn!("Cannot persist corrector function {} — no [[worker]] entries", func);
        return;
    };

    let mut updated = 0usize;
    for worker in workers.iter_mut() {
        let Some(row) = worker.as_table_mut() else { continue };
        let role = row.get("role").and_then(|v| v.as_str()).unwrap_or("");
        if role != "corrector" && role != "correct" {
            continue;
        }

        let mut funcs = row
            .get("corrector_functions")
            .and_then(|v| v.as_table())
            .cloned()
            .unwrap_or_default();
        funcs.insert(func.to_string(), toml::Value::Boolean(enabled));
        row.insert("corrector_functions".to_string(), toml::Value::Table(funcs));
        updated += 1;
    }

    if updated == 0 {
        warn!("No corrector worker found while setting {}={}", func, enabled);
        return;
    }

    if let Err(e) = cluster_store::write_config(&table) {
        warn!("Failed persisting corrector function {}={}: {}", func, enabled, e);
        return;
    }
    info!("Persisted corrector function {}={} on {} worker(s)", func, enabled, updated);
}

/// POST /validate { "prompt": "optional" }
async fn validate_endpoint(
    State(state): State<AppState>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let prompt = body
        .get("prompt")
        .and_then(|v| v.as_str())
        .unwrap_or("The quick brown fox jumps over the lazy dog. In Rust, a vector is");

    let config = validator::ValidatorConfig {
        main_endpoint: state.config.coder_url.clone(),
        ref_endpoint: state.config.validator_url.clone(),
        n_tokens: 10,
        min_agreement: 0.4,
    };

    let result = validator::run_validation(&config, prompt).await;
    Json(serde_json::to_value(&result).unwrap_or_default())
}

/// GET /validate/ping — quick liveness check of both main engine and P1000.
async fn validate_ping(State(state): State<AppState>) -> Json<serde_json::Value> {
    let main_up = validator::ping(&state.config.coder_url).await;
    let p1000_up = validator::ping(&state.config.validator_url).await;

    let main_tps = if main_up {
        validator::benchmark_tps(&state.config.coder_url, 5).await
    } else {
        None
    };
    let p1000_tps = if p1000_up {
        validator::benchmark_tps(&state.config.validator_url, 5).await
    } else {
        None
    };

    Json(serde_json::json!({
        "main_engine": {
            "url": state.config.coder_url,
            "online": main_up,
            "tps": main_tps,
        },
        "p1000_validator": {
            "url": state.config.validator_url,
            "online": p1000_up,
            "tps": p1000_tps,
        },
        "status": if main_up { "ok" } else { "main_engine_down" },
    }))
}

async fn nvidia_handoff(
    State(state): State<AppState>,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    let message = body.get("message").and_then(|v| v.as_str()).unwrap_or("");
    let safe_mode = body.get("safe_mode").and_then(|v| v.as_bool()).unwrap_or(false);

    if message.is_empty() {
        return Json(serde_json::json!({"error": "message is required"}));
    }

    // Pass 1: Local Nvidia endpoint
    let local_endpoint = state.config.coder_url.clone();
    
    // Pass 2: The polisher endpoint
    let polisher_endpoint = routing::endpoint_for_role("polisher")
        .unwrap_or_else(|| "http://127.0.0.1:5012".to_string());

    info!("NVIDIA Handoff Pass 1: Dispatching to {}", local_endpoint);
    
    let config_pass1 = agent_dispatch::AgentConfig {
        endpoint_url: local_endpoint,
        project_root: paths::project_root(),
        nautivecs_url: state.config.nautivecs_url.clone(),
        wso_url: state.config.wso_url.clone(),
        mcp_url: mcp_endpoint_from_config(),
        max_tokens: 4096,
        temperature: 0.3,
        safe_mode,
    };
    
    let pass1_result = agent_dispatch::run_agent_loop(&config_pass1, message).await;
    
    info!("NVIDIA Handoff Pass 2: Polishing via {}", polisher_endpoint);
    
    let config_pass2 = agent_dispatch::AgentConfig {
        endpoint_url: polisher_endpoint,
        project_root: paths::project_root(),
        nautivecs_url: state.config.nautivecs_url.clone(),
        wso_url: state.config.wso_url.clone(),
        mcp_url: mcp_endpoint_from_config(),
        max_tokens: 4096,
        temperature: 0.1,
        safe_mode,
    };
    
    let polisher_message = format!(
        "Please refine and polish the following output from the previous local model pass:\n\n{}",
        pass1_result
    );
    
    let final_result = agent_dispatch::run_agent_loop(&config_pass2, &polisher_message).await;
    
    Json(serde_json::json!({
        "pass1_output": pass1_result,
        "final_output": final_result
    }))
}

#[derive(Deserialize)]
struct WorkflowStep {
    role: String,
    #[serde(default)]
    hint_for_next: String,
}

#[derive(Deserialize)]
struct WorkflowRequest {
    message: String,
    workflow: Vec<WorkflowStep>,
    #[serde(default)]
    log_errors: bool,
    #[serde(default)]
    safe_mode: bool,
}

async fn workflow_execute(
    State(state): State<AppState>,
    Json(req): Json<WorkflowRequest>,
) -> Json<serde_json::Value> {
    if req.message.is_empty() {
        return Json(serde_json::json!({"error": "message is required"}));
    }

    if req.workflow.is_empty() {
        return Json(serde_json::json!({"error": "workflow must contain at least one step"}));
    }

    let mut current_message = req.message.clone();
    let mut step_outputs = Vec::new();

    for (i, step) in req.workflow.iter().enumerate() {
        let endpoint = routing::endpoint_for_role(&step.role)
            .unwrap_or_else(|| state.config.coder_url.clone());

        info!("Workflow Step {}: Dispatching to role '{}' ({})", i + 1, step.role, endpoint);

        let config = agent_dispatch::AgentConfig {
            endpoint_url: endpoint,
            project_root: paths::project_root(),
            nautivecs_url: state.config.nautivecs_url.clone(),
            wso_url: state.config.wso_url.clone(),
            mcp_url: mcp_endpoint_from_config(),
            max_tokens: 4096,
            temperature: 0.3,
            safe_mode: req.safe_mode,
        };

        let result = agent_dispatch::run_agent_loop(&config, &current_message).await;
        
        if req.log_errors && (result.contains("Error:") || result.contains("Correction:")) {
            let add_url = state.config.nautivecs_url.replace("/query", "/ingest");
            let payload = serde_json::json!({
                "text": format!("Workflow Error/Correction from role {}:\n{}", step.role, result),
                "tags": "workflow,error,correction",
                "source": "workflow_engine"
            });
            let client = reqwest::Client::new();
            let _ = client.post(&add_url).json(&payload).send().await;
            info!("Logged error/correction to nautivecs for step {}", i + 1);
        }

        step_outputs.push(serde_json::json!({
            "step": i + 1,
            "role": step.role.clone(),
            "output": result.clone()
        }));

        if !step.hint_for_next.is_empty() {
            current_message = format!("{}\n\nPrevious Output:\n{}\n", step.hint_for_next, result);
        } else {
            current_message = result;
        }
    }

    Json(serde_json::json!({
        "status": "success",
        "steps": step_outputs,
        "final_output": current_message
    }))
}

#[derive(serde::Deserialize)]
pub struct PlanRequest {
    pub message: String,
}

async fn workflow_plan(
    State(_state): State<AppState>,
    Json(req): Json<PlanRequest>,
) -> Json<serde_json::Value> {
    // Generate a mock response for the planner to demonstrate UI behavior
    Json(serde_json::json!({
        "proposed_template": "coder_level2.json",
        "missing_context": [
            "What framework should the coder use for the frontend?",
            "What database backend is preferred?"
        ],
        "original_prompt": req.message,
        "action": "Please fill in the missing context below before proceeding."
    }))
}

// ── Lake Worker (CPU Idle Satellite Tile Processing) ──────────────────────
// GET /cluster/lake-worker — check if lake_coverage_service.py is running
async fn lake_worker_status() -> Json<serde_json::Value> {
    let output = std::process::Command::new("bash")
        .arg("-c")
        .arg("pgrep -f lake_coverage_service.py | head -1")
        .output();
    let running = match output {
        Ok(out) => {
            let pid = String::from_utf8_lossy(&out.stdout).trim().to_string();
            pid.parse::<u32>().is_ok()
        }
        Err(_) => false,
    };
    Json(serde_json::json!({
        "running": running,
        "name": "CPU Idle Worker · Satellite Tile Processing",
        "description": "Background task using spare Xeon cycles for GDAL/raster work",
        "script": "lake_coverage_service.py"
    }))
}

// POST /cluster/lake-worker { "action": "start" | "stop" }
async fn lake_worker_action(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let action = body.get("action").and_then(|v| v.as_str()).unwrap_or("start");
    match action {
        "start" => {
            let check = std::process::Command::new("bash")
                .arg("-c")
                .arg("pgrep -f lake_coverage_service.py | head -1")
                .output();
            let already_running = match check {
                Ok(out) => {
                    let pid = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    pid.parse::<u32>().is_ok()
                }
                Err(_) => false,
            };
            if already_running {
                return Json(serde_json::json!({"message": "Lake worker already running", "running": true}));
            }
            let cmd = "nohup /usr/bin/python3 /codebase/repos/wreckhunter2000-1/scripts/lake_coverage_service.py start --poll 30 --limit 200 > /tmp/lake_worker.log 2>&1 & echo $!";
            let result = std::process::Command::new("bash")
                .arg("-c")
                .arg(cmd)
                .output();
            match result {
                Ok(out) => {
                    let pid = String::from_utf8_lossy(&out.stdout).trim().to_string();
                    info!("Lake worker started: PID {}", pid);
                    Json(serde_json::json!({
                        "message": format!("Lake worker started (PID {})", pid),
                        "running": true,
                        "pid": pid
                    }))
                }
                Err(e) => Json(serde_json::json!({
                    "error": format!("Failed to start lake worker: {}", e),
                    "running": false
                })),
            }
        }
        "stop" => {
            let _ = std::process::Command::new("bash")
                .arg("-c")
                .arg("pkill -f lake_coverage_service.py")
                .output();
            info!("Lake worker stopped");
            Json(serde_json::json!({
                "message": "Lake worker stopped",
                "running": false
            }))
        }
        _ => Json(serde_json::json!({"error": "action must be 'start' or 'stop'"})),
    }
}

// ── Dispatch API (Multi-GPU Routing from dispatch.html) ────────────────────

/// POST /cluster/dispatch/launch
/// Launch models on selected GPUs based on dispatch.html configuration.
/// Body: { "name": "routing-123", "assignments": [...], "endpoints": [...], "rounds": [...] }
async fn dispatch_launch(Json(body): Json<serde_json::Value>) -> Json<serde_json::Value> {
    let name = body.get("name").and_then(|v| v.as_str()).unwrap_or("dispatch");
    let assignments = body.get("assignments").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    
    info!("Dispatch launch '{}' with {} GPU groups", name, assignments.len());
    
    let mut launched = Vec::new();
    let mut failed = Vec::new();
    
    // Launch each GPU group assignment
    for (idx, assignment) in assignments.iter().enumerate() {
        let gpu_ids: Vec<i64> = assignment
            .get("gpuIds")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_i64()).collect())
            .unwrap_or_default();
        
        let role = assignment.get("role").and_then(|v| v.as_str()).unwrap_or("general");
        let model = assignment.get("model").and_then(|v| v.as_str()).unwrap_or("");
        let is_set = assignment.get("set").and_then(|v| v.as_bool()).unwrap_or(false);
        
        if !is_set || model.is_empty() || gpu_ids.is_empty() {
            continue;
        }
        
        // Generate port based on first GPU ID
        let port = 5000 + gpu_ids[0] * 10;
        
        // Determine engine - use koboldcpp for multi-GPU, llama-server for single GPU
        let engine = if gpu_ids.len() > 1 { "koboldcpp" } else { "llama-server" };
        let backend = if gpu_ids.len() > 1 { "vulkan" } else { "cuda" };
        
        // Build launch command
        let cmd = if engine == "koboldcpp" {
            let tensor_split = vec!["1.0"; gpu_ids.len()].join(",");
            format!(
                "setsid /home/cesarops/koboldcpp --model {} --port {} --usevulkan {} \
                 --gpulayers 99 --contextsize 8192 --threads 4 --tensor_split {} \
                 --quiet > /tmp/dispatch_group_{}.log 2>&1 < /dev/null & disown",
                model, port, gpu_ids[0], tensor_split, idx
            )
        } else {
            // llama-server for single GPU
            let gpu_layers = 99;
            format!(
                "setsid llama-server --model {} --port {} --gpu-layers {} \
                 --ctx-size 8192 --threads 4 -ngl {} > /tmp/dispatch_group_{}.log 2>&1 < /dev/null & disown",
                model, port, gpu_layers, gpu_layers, idx
            )
        };
        
        info!("Launching group {}: GPUs {:?}, role={}, model={}, port={}", 
              idx, gpu_ids, role, model.split('/').last().unwrap_or(model), port);
        
        match std::process::Command::new("bash").arg("-c").arg(&cmd).output() {
            Ok(_) => {
                launched.push(serde_json::json!({
                    "group": idx,
                    "gpus": gpu_ids,
                    "role": role,
                    "model": model.split('/').last().unwrap_or(model),
                    "port": port,
                    "endpoint": format!("http://127.0.0.1:{}", port),
                    "engine": engine
                }));
            }
            Err(e) => {
                failed.push(serde_json::json!({
                    "group": idx,
                    "error": e.to_string()
                }));
            }
        }
    }
    
    let endpoints = body.get("endpoints").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let rounds = body.get("rounds").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    
    // Save routing configuration
    let config_path = "/tmp/dispatch_routing.json";
    let routing_config = serde_json::json!({
        "name": name,
        "launched_at": chrono::Utc::now().to_rfc3339(),
        "assignments": launched,
        "endpoints": endpoints,
        "rounds": rounds,
    });
    let _ = std::fs::write(config_path, serde_json::to_string_pretty(&routing_config).unwrap_or_default());
    
    info!("Dispatch '{}' launched: {} groups, {} failed", name, launched.len(), failed.len());
    
    Json(serde_json::json!({
        "message": format!("Launched {} GPU groups for '{}'", launched.len(), name),
        "launched": launched,
        "failed": failed,
        "config_saved": config_path
    }))
}

/// POST /cluster/dispatch/stop
/// Stop all dispatch workers (but keep P106/P1000 if configured as always-on)
async fn dispatch_stop() -> Json<serde_json::Value> {
    info!("Dispatch stop requested");
    
    // Kill all inference engines (will spare P106/P1000 if they were not launched by dispatch)
    let _ = std::process::Command::new("bash")
        .arg("-c")
        .arg("pkill -f 'koboldcpp.*--port' ; pkill -f 'llama-server.*--port' ; true")
        .output();
    
    // Clean up dispatch routing config
    let config_path = "/tmp/dispatch_routing.json";
    let _ = std::fs::remove_file(config_path);
    
    info!("Dispatch workers stopped");
    
    Json(serde_json::json!({
        "message": "Dispatch workers stopped (P106/P1000 preserved if running)",
        "stopped_at": chrono::Utc::now().to_rfc3339()
    }))
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter("cesarops_forge_v2=info")
        .init();

    let config = ForgeConfig {
        coder_url: "http://127.0.0.1:5001".to_string(),  // Qwen3.6 on P100s
        thinker_url: "http://127.0.0.1:5557".to_string(),       // DeepSeek-R1 7B on Xeon CPU (thinker)
        corrector_url: "http://0.0.0.0:0".to_string(), // DISABLED — corrector severed, skip_corrector=true in tuning
        nautivecs_url: "http://127.0.0.1:5003/query".to_string(),
        wso_url: "http://127.0.0.1:5010/search".to_string(),
        project_root: paths::project_root(),
        validator_url: "http://100.102.158.111:5571".to_string(), // P1000 TinyLlama — speed+accuracy canary
    };

    let state = AppState {
        conversation: Arc::new(Mutex::new(Vec::new())),
        config: Arc::new(config),
        interrupt: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        send_busy: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        steering: Arc::new(Mutex::new(Vec::new())),
        lanes: stream_lanes::LaneStore::new(),
    };

    let app = Router::new()
        .route("/", get(index))
        .route("/cluster", get(cluster_panel))
        .route("/wall", get(wall_dashboard))
        .route("/scores", get(get_scores))
        .route("/health", get(health))
        .route("/send", post(send_message))
        .route("/lanes", get(list_lanes))
        .route("/lanes/activity", get(lanes_activity))
        .route("/lanes/{lane_id}/role", post(set_lane_role))
        .route("/roles", get(get_roles))
        .route("/clear", post(clear))
        .route("/clear/lane", post(clear_lane))
        .route("/interrupt", post(interrupt))
        .route("/steer", post(steer))
        .route("/monitor", get(monitor))
        .route("/cluster/config", get(get_cluster_config).post(save_cluster_config))
        .route("/cluster/config/full", get(get_cluster_config_full))
        .route("/cluster/gpus", get(get_gpu_fleet))
        .route("/cluster/gpu/{gpu_id}/apply", post(apply_gpu))
        .route("/cluster/fleet/clear-all", post(fleet_clear_all))
        .route("/cluster/fleet/dispatch", post(fleet_dispatch))
        .route("/cluster/routing", get(get_routing_presets))
        .route("/cluster/routing/preset/{preset_id}", post(apply_routing_preset))
        .route("/cluster/launch/candle", post(launch_candle_big))
        .route("/cluster/models", get(list_available_models))
        .route("/cluster/fit-recommendations", post(model_fit_recommendations))
        .route("/cluster/preset/config", get(get_preset_config).post(save_preset_config))
        .route("/cluster/preset/activate", post(activate_preset))
        .route("/cluster/preset/launch", post(launch_preset))
        .route("/cluster/preset/deactivate", post(deactivate_preset))
        .route("/cluster/freeform/apply", post(apply_freeform))
        .route("/cluster/agent/run", post(run_agent_task))
        .route("/cluster/corrector/connect", post(corrector_connect))
        .route("/cluster/corrector/disconnect", post(corrector_disconnect))
        .route("/validate", post(validate_endpoint))
        .route("/validate/ping", get(validate_ping))
        .route("/cluster/worker/{name}/start", post(start_worker))
        .route("/cluster/worker/{name}/stop", post(stop_worker))
        .route("/cluster/worker/{name}/status", get(worker_status))
        .route("/cluster/start-all", post(start_all_workers))
        .route("/cluster/stop-all", post(stop_all_workers))
        .route("/cluster/discover", get(discover_nodes))
        // ── New per-card control routes ──────────────────────────────────
        .route("/cluster/worker/{name}/apply",         post(worker_apply))
        .route("/cluster/worker/{name}/set_injection", post(worker_set_injection))
        .route("/cluster/worker/{name}/set_backend",   post(worker_set_backend))
        .route("/cluster/corrector/set_function",      post(corrector_set_function))
        .route("/cluster/engines",                     get(get_available_engines))
        .route("/cluster/memory_pool/create",          post(memory_pool_create))
        .route("/cluster/nvidia/handoff",              post(nvidia_handoff))
        .route("/cluster/workflow/execute",            post(workflow_execute))
        .route("/cluster/workflow/plan",               post(workflow_plan))
        .route("/cluster/lake-worker",                 get(lake_worker_status).post(lake_worker_action))
        // ── Dispatch endpoints (for dispatch.html multi-GPU routing) ────
        .route("/cluster/dispatch/launch",             post(dispatch_launch))
        .route("/cluster/dispatch/stop",               post(dispatch_stop))
        .with_state(state);

    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], 9100));
    info!("cesarops-forge-v2 (Self-Healing Knowledge Translator) on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
