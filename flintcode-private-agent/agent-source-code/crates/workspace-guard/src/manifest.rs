use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Workspace manifest loaded from workspace-manifest.toml
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub workspace_root: PathBuf,
    #[serde(default)]
    pub readable: Vec<String>,
    #[serde(default)]
    pub writable: Vec<String>,
    #[serde(default)]
    pub denied: Vec<String>,
    #[serde(default = "default_max_single")]
    pub max_single_file_bytes: u64,
    #[serde(default = "default_max_total")]
    pub max_total_read_bytes: u64,
    #[serde(default)]
    pub follow_symlinks: bool,
    #[serde(default)]
    pub recursive_discovery: bool,
}

fn default_max_single() -> u64 {
    180_000
}
fn default_max_total() -> u64 {
    500_000
}

impl Default for Manifest {
    fn default() -> Self {
        Self {
            workspace_root: PathBuf::from("."),
            readable: vec![],
            writable: vec![],
            denied: vec![
                ".env".to_string(),
                "*.pem".to_string(),
                "*.key".to_string(),
                "**/secrets/**".to_string(),
                "**/.git/config".to_string(),
            ],
            max_single_file_bytes: 180_000,
            max_total_read_bytes: 500_000,
            follow_symlinks: false,
            recursive_discovery: false,
        }
    }
}
