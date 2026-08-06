//! Three parallel Forge lanes with cross-lane activity monitoring.

use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::RwLock;

pub const LANE_IDS: &[&str] = &["lane-a", "lane-b", "lane-c"];

#[derive(Clone, Serialize, Deserialize)]
pub struct ActivityLine {
    pub ts: u64,
    pub lane: String,
    pub kind: String,
    pub text: String,
}

#[derive(Clone, Default)]
pub struct LaneStore {
    pub activity: Arc<RwLock<Vec<ActivityLine>>>,
    /// Per-lane conversation history keys: lane-a, lane-b, lane-c
    pub conversations: Arc<RwLock<std::collections::HashMap<String, Vec<crate::translator::Message>>>>,
}

impl LaneStore {
    pub fn new() -> Self {
        Self {
            activity: Arc::new(RwLock::new(Vec::new())),
            conversations: Arc::new(RwLock::new(std::collections::HashMap::new())),
        }
    }

    pub async fn log(&self, lane: &str, kind: &str, text: &str) {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let line = ActivityLine {
            ts,
            lane: lane.to_string(),
            kind: kind.to_string(),
            text: text.chars().take(240).collect(),
        };
        let mut log = self.activity.write().await;
        log.push(line);
        if log.len() > 500 {
            let drain = log.len() - 400;
            log.drain(0..drain);
        }
    }

    pub async fn snapshot(&self) -> Vec<ActivityLine> {
        self.activity.read().await.clone()
    }

    pub async fn push_message(&self, lane: &str, msg: crate::translator::Message) {
        let mut convs = self.conversations.write().await;
        convs.entry(lane.to_string()).or_default().push(msg);
    }

    pub async fn get_conversation(&self, lane: &str) -> Vec<crate::translator::Message> {
        self.conversations
            .read()
            .await
            .get(lane)
            .cloned()
            .unwrap_or_default()
    }

    pub async fn set_conversation(&self, lane: &str, msgs: Vec<crate::translator::Message>) {
        let mut convs = self.conversations.write().await;
        convs.insert(lane.to_string(), msgs);
    }

    pub async fn clear_lane(&self, lane: &str) {
        let mut convs = self.conversations.write().await;
        convs.remove(lane);
    }
}

pub fn list_lanes_json() -> serde_json::Value {
    let lanes = crate::routing::load_lanes_state();
    serde_json::json!({
        "lanes": LANE_IDS.iter().map(|id| {
            let role = lanes.lane_roles.get(*id).cloned().unwrap_or_else(|| "general".into());
            let endpoint = crate::routing::resolve_lane_coder_url(id);
            serde_json::json!({
                "id": id,
                "label": match *id {
                    "lane-a" => "Path A",
                    "lane-b" => "Path B (Coding)",
                    "lane-c" => "Path C",
                    _ => id,
                },
                "role": role,
                "endpoint": endpoint,
            })
        }).collect::<Vec<_>>(),
        "netdata_url": crate::routing::netdata_url(),
        "roles": crate::routing::LANE_ROLE_CATALOG.iter().map(|(id,l)| serde_json::json!({"id": id, "label": l})).collect::<Vec<_>>(),
    })
}
