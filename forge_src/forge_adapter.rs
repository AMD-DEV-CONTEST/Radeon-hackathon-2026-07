use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ForgeRuntime {
    V2,
    V3,
}

impl ForgeRuntime {
    pub fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "v2" | "forge-v2" | "forge_v2" => Ok(Self::V2),
            "v3" | "forge-v3" | "forge_v3" => Ok(Self::V3),
            other => Err(format!("invalid runtime '{}': expected 'v2' or 'v3'", other)),
        }
    }

    pub fn as_key(self) -> &'static str {
        match self {
            Self::V2 => "v2",
            Self::V3 => "v3",
        }
    }

    pub fn display_name(self) -> &'static str {
        match self {
            Self::V2 => "Forge V2",
            Self::V3 => "Forge V3",
        }
    }
}

#[derive(Clone, Debug)]
pub struct MissionSubmission {
    pub mission_id: String,
    pub run_id: String,
    pub runtime: ForgeRuntime,
}

#[derive(Clone, Debug)]
pub struct MissionRecord {
    pub mission_id: String,
    pub run_id: String,
    pub runtime: ForgeRuntime,
    pub status: String,
    pub stage: String,
    pub trace: Vec<String>,
    pub artifacts: Vec<String>,
}

pub struct ForgeAdapter {
    runtime: RwLock<ForgeRuntime>,
    missions: Mutex<HashMap<String, MissionRecord>>,
    seq: AtomicU64,
    runtime_state_path: String,
    runtime_audit_log_path: String,
}

impl ForgeAdapter {
    pub fn new(initial_runtime: ForgeRuntime, runtime_state_path: String, runtime_audit_log_path: String) -> Self {
        Self {
            runtime: RwLock::new(initial_runtime),
            missions: Mutex::new(HashMap::new()),
            seq: AtomicU64::new(1),
            runtime_state_path,
            runtime_audit_log_path,
        }
    }

    pub fn current_runtime(&self) -> ForgeRuntime {
        *self.runtime.read().unwrap_or_else(|e| e.into_inner())
    }

    pub fn runtime_label(&self) -> &'static str {
        self.current_runtime().display_name()
    }

    pub fn submit_mission(&self) -> MissionSubmission {
        let runtime = self.current_runtime();
        let now = now_unix();
        let seq = self.seq.fetch_add(1, Ordering::Relaxed);
        let mission_id = format!("mission-{}-{}-{}", runtime.as_key(), now, seq);
        let run_id = format!("run-{}-{}", now, seq);
        let trace = vec![
            format!("{} runtime selected: {}", now, runtime.display_name()),
            format!("{} mission submitted", now),
        ];
        let record = MissionRecord {
            mission_id: mission_id.clone(),
            run_id: run_id.clone(),
            runtime,
            status: "Running".to_string(),
            stage: "Dispatched".to_string(),
            trace,
            artifacts: Vec::new(),
        };
        self.missions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(mission_id.clone(), record);
        MissionSubmission {
            mission_id,
            run_id,
            runtime,
        }
    }

    pub fn complete_mission(
        &self,
        mission_id: &str,
        final_stage: &str,
        artifacts: Vec<String>,
        extra_trace: Vec<String>,
    ) -> Result<(), String> {
        let mut missions = self.missions.lock().unwrap_or_else(|e| e.into_inner());
        let Some(record) = missions.get_mut(mission_id) else {
            return Err(format!("mission '{}' not found", mission_id));
        };
        record.status = "Completed".to_string();
        record.stage = final_stage.to_string();
        record.artifacts = artifacts;
        for line in extra_trace {
            record.trace.push(line);
        }
        record
            .trace
            .push(format!("{} mission completed", now_unix()));
        Ok(())
    }

    pub fn fail_mission(&self, mission_id: &str, error: &str) -> Result<(), String> {
        let mut missions = self.missions.lock().unwrap_or_else(|e| e.into_inner());
        let Some(record) = missions.get_mut(mission_id) else {
            return Err(format!("mission '{}' not found", mission_id));
        };
        record.status = "Failed".to_string();
        record.stage = "Failed".to_string();
        record.trace.push(format!("{} mission failed: {}", now_unix(), error));
        Ok(())
    }

    pub fn get_status(&self, mission_id: &str) -> Option<MissionRecord> {
        self.missions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(mission_id)
            .cloned()
    }

    pub fn get_trace(&self, mission_id: &str) -> Option<Vec<String>> {
        self.get_status(mission_id).map(|r| r.trace)
    }

    pub fn get_artifacts(&self, mission_id: &str) -> Option<Vec<String>> {
        self.get_status(mission_id).map(|r| r.artifacts)
    }

    pub fn cancel_mission(&self, mission_id: &str) -> Result<(), String> {
        let mut missions = self.missions.lock().unwrap_or_else(|e| e.into_inner());
        let Some(record) = missions.get_mut(mission_id) else {
            return Err(format!("mission '{}' not found", mission_id));
        };
        if record.status == "Completed" {
            return Err("mission already completed".to_string());
        }
        record.status = "Cancelled".to_string();
        record.stage = "Cancelled".to_string();
        record.trace.push(format!("{} mission cancelled", now_unix()));
        Ok(())
    }

    pub fn health(&self) -> String {
        let mission_count = self
            .missions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .len();
        format!(
            "ok runtime={} runtime_label={} missions_tracked={}",
            self.current_runtime().as_key(),
            self.runtime_label(),
            mission_count
        )
    }

    pub fn switch_runtime(&self, next: ForgeRuntime, reason: &str) -> Result<ForgeRuntime, String> {
        let mut lock = self.runtime.write().unwrap_or_else(|e| e.into_inner());
        let previous = *lock;
        *lock = next;
        self.persist_runtime(next)?;
        self.append_audit(previous, next, reason)?;
        Ok(previous)
    }

    fn persist_runtime(&self, runtime: ForgeRuntime) -> Result<(), String> {
        let path = Path::new(&self.runtime_state_path);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::write(path, runtime.as_key()).map_err(|e| e.to_string())
    }

    fn append_audit(&self, previous: ForgeRuntime, next: ForgeRuntime, reason: &str) -> Result<(), String> {
        let path = Path::new(&self.runtime_audit_log_path);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut existing = fs::read_to_string(path).unwrap_or_default();
        existing.push_str(&format!(
            "{} runtime_switch {} -> {} reason={}\n",
            now_unix(),
            previous.as_key(),
            next.as_key(),
            reason.replace('\n', " ")
        ));
        fs::write(path, existing).map_err(|e| e.to_string())
    }
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn adapter() -> ForgeAdapter {
        ForgeAdapter::new(
            ForgeRuntime::V2,
            "/tmp/forge_runtime_state_test.txt".to_string(),
            "/tmp/forge_runtime_audit_test.log".to_string(),
        )
    }

    #[test]
    fn runtime_parse_accepts_v2_and_v3() {
        assert_eq!(ForgeRuntime::parse("v2").unwrap(), ForgeRuntime::V2);
        assert_eq!(ForgeRuntime::parse("v3").unwrap(), ForgeRuntime::V3);
    }

    #[test]
    fn runtime_parse_rejects_invalid() {
        assert!(ForgeRuntime::parse("bad-runtime").is_err());
    }

    #[test]
    fn submit_uses_selected_runtime() {
        let adapter = adapter();
        let first = adapter.submit_mission();
        assert_eq!(first.runtime, ForgeRuntime::V2);
        adapter
            .switch_runtime(ForgeRuntime::V3, "test")
            .expect("switch failed");
        let second = adapter.submit_mission();
        assert_eq!(second.runtime, ForgeRuntime::V3);
    }

    #[test]
    fn status_and_artifact_passthrough() {
        let adapter = adapter();
        let submitted = adapter.submit_mission();
        adapter
            .complete_mission(
                &submitted.mission_id,
                "HumanReviewBoundary",
                vec!["/tmp/evidence.json".to_string()],
                vec!["trace line".to_string()],
            )
            .expect("complete failed");
        let status = adapter.get_status(&submitted.mission_id).expect("missing status");
        assert_eq!(status.status, "Completed");
        assert_eq!(status.stage, "HumanReviewBoundary");
        assert_eq!(status.artifacts, vec!["/tmp/evidence.json".to_string()]);
    }

    #[test]
    fn cancel_updates_status() {
        let adapter = adapter();
        let submitted = adapter.submit_mission();
        adapter.cancel_mission(&submitted.mission_id).expect("cancel failed");
        let status = adapter.get_status(&submitted.mission_id).expect("missing status");
        assert_eq!(status.status, "Cancelled");
    }
}
