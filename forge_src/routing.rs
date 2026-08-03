//! Role → endpoint registry and lane routing.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tracing::info;

use crate::paths;

pub const LANE_ROLE_CATALOG: &[(&str, &str)] = &[
    ("idle", "idle"),
    ("coder", "coder"),
    ("thinker", "thinker"),
    ("reviewer", "reviewer"),
    ("corrector", "corrector"),
    ("polisher", "polisher"),
    ("validator", "validator"),
    ("general", "general"),
    ("coding", "coding"),
    ("bootstrap", "bootstrap"),
    ("fleet_command", "fleet command center"),
];

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct RoutingState {
    pub chat_agent: String,
    pub coder_endpoint: String,
    pub reviewer_endpoint: String,
    pub thinker_endpoint: String,
    pub corrector_endpoint: String,
    pub draft_endpoint: String,
    #[serde(default)]
    pub active_preset_id: String,
    #[serde(default)]
    pub lane_roles: HashMap<String, String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct LanesState {
    #[serde(default)]
    pub lane_roles: HashMap<String, String>,
}

pub fn load_routing_state() -> RoutingState {
    std::fs::read_to_string(paths::routing_state_path())
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save_routing_state(state: &RoutingState) {
    let _ = std::fs::write(
        paths::routing_state_path(),
        serde_json::to_string_pretty(state).unwrap_or_default(),
    );
}

pub fn load_lanes_state() -> LanesState {
    std::fs::read_to_string(paths::lanes_state_path())
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| default_lanes_state())
}

pub fn save_lanes_state(state: &LanesState) {
    let _ = std::fs::write(
        paths::lanes_state_path(),
        serde_json::to_string_pretty(state).unwrap_or_default(),
    );
}

pub fn default_lanes_state() -> LanesState {
    let mut lane_roles = HashMap::new();
    lane_roles.insert("lane-a".to_string(), "general".to_string());
    lane_roles.insert("lane-b".to_string(), "coding".to_string());
    lane_roles.insert("lane-c".to_string(), "thinker".to_string());
    LanesState { lane_roles }
}

/// Load [roles] table + [nicknames] + [[agent]] from cluster_config.toml.
pub fn load_role_endpoints() -> HashMap<String, String> {
    let mut map = HashMap::new();
    let content = std::fs::read_to_string(paths::cluster_config_path()).unwrap_or_default();
    let table: toml::Table = content.parse().unwrap_or_default();

    if let Some(workers) = table.get("worker").and_then(|v| v.as_array()) {
        for w in workers {
            if let Some(t) = w.as_table() {
                let role = t.get("role").and_then(|v| v.as_str()).unwrap_or("");
                let host = t.get("host").and_then(|v| v.as_str()).unwrap_or("127.0.0.1");
                let port = t.get("port").and_then(|v| v.as_integer()).unwrap_or(5010);
                
                let resolved_host = if host == "local" { "127.0.0.1" } else { host };
                let ep = format!("http://{}:{}", resolved_host, port);
                
                if !role.is_empty() {
                    map.insert(role.to_string(), ep);
                }
            }
        }
    }

    if let Some(nick) = table.get("nicknames").and_then(|v| v.as_table()) {
        for (k, v) in nick {
            if let Some(ep) = v.as_str() {
                map.entry(k.clone()).or_insert(ep.to_string());
            }
        }
    }

    if let Some(agents) = table.get("agent").and_then(|v| v.as_array()) {
        for a in agents {
            if let Some(t) = a.as_table() {
                let name = t.get("name").and_then(|v| v.as_str()).unwrap_or("");
                let ep = t.get("endpoint").and_then(|v| v.as_str()).unwrap_or("");
                if !name.is_empty() && !ep.is_empty() {
                    map.entry(name.to_string()).or_insert(ep.to_string());
                }
            }
        }
    }

    map
}

pub fn endpoint_for_role(role: &str) -> Option<String> {
    let roles = load_role_endpoints();
    roles.get(role).cloned()
}

pub fn resolve_lane_coder_url(lane_id: &str) -> String {
    let lanes = load_lanes_state();
    let role = lanes
        .lane_roles
        .get(lane_id)
        .cloned()
        .unwrap_or_else(|| "general".to_string());

    if let Some(ep) = endpoint_for_role(&role) {
        return ep;
    }

    // Robust fallbacks so coding lanes can still run if one role endpoint is down.
    let roles = load_role_endpoints();
    let fallback_chain: &[&str] = match role.as_str() {
        "coding" => &["polisher", "coder", "reviewer", "general"],
        "general" => &["coder", "polisher", "reviewer"],
        "coder" => &["polisher", "reviewer", "general"],
        "polisher" => &["coder", "reviewer", "general"],
        _ => &["coder", "polisher", "reviewer", "general"],
    };
    for r in fallback_chain {
        if let Some(ep) = roles.get(*r) {
            return ep.clone();
        }
    }

    let routing = load_routing_state();
    if !routing.coder_endpoint.is_empty() {
        return routing.coder_endpoint;
    }

    load_role_endpoints()
        .get("coder")
        .cloned()
        .unwrap_or_else(|| "http://127.0.0.1:5001".to_string())
}

pub fn set_lane_role(lane_id: &str, role: &str) {
    let mut lanes = load_lanes_state();
    lanes.lane_roles.insert(lane_id.to_string(), role.to_string());
    save_lanes_state(&lanes);
    info!("Lane {} → role {}", lane_id, role);
}

pub fn netdata_url() -> Option<String> {
    let content = std::fs::read_to_string(paths::cluster_config_path()).unwrap_or_default();
    let table: toml::Table = content.parse().unwrap_or_default();
    table
        .get("monitoring")
        .and_then(|m| m.get("netdata_url"))
        .and_then(|v| v.as_str())
        .map(String::from)
}
