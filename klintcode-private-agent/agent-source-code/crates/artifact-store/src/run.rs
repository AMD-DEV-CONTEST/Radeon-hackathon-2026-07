use anyhow::Result;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use tracing::info;

/// Manages the artifact directory for a single run.
#[derive(Clone)]
pub struct RunArtifacts {
    pub run_id: String,
    pub root: PathBuf,
}

impl RunArtifacts {
    /// Create a new run directory under the given root.
    pub async fn create(runs_root: &Path, run_id: &str) -> Result<Self> {
        let root = runs_root.join(run_id);
        tokio::fs::create_dir_all(&root).await?;
        info!(run_id, path = %root.display(), "Run directory created");
        Ok(Self {
            run_id: run_id.to_string(),
            root,
        })
    }

    /// Save the run configuration.
    pub async fn save_config(&self, config: &impl Serialize) -> Result<()> {
        let path = self.root.join("run-config.json");
        let json = serde_json::to_string_pretty(config)?;
        tokio::fs::write(&path, &json).await?;
        Ok(())
    }

    /// Append an event to events.jsonl.
    pub async fn append_event(&self, event: &impl Serialize) -> Result<()> {
        use tokio::io::AsyncWriteExt;
        let path = self.root.join("events.jsonl");
        let mut file = tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path).await?;
        let json = serde_json::to_string(event)?;
        file.write_all(format!("{json}\n").as_bytes()).await?;
        Ok(())
    }

    /// Create an attempt directory and return the path.
    pub async fn create_attempt(&self, attempt: u8) -> Result<PathBuf> {
        let dir = self.root.join(format!("attempt-{attempt:02}"));
        tokio::fs::create_dir_all(&dir).await?;
        Ok(dir)
    }

    /// Save a candidate artifact for an attempt.
    pub async fn save_candidate(&self, attempt: u8, content: &str) -> Result<PathBuf> {
        let dir = self.create_attempt(attempt).await?;
        let path = dir.join("candidate");
        tokio::fs::write(&path, content).await?;
        Ok(path)
    }

    /// Save the final artifact.
    pub async fn save_final_artifact(&self, content: &str) -> Result<PathBuf> {
        let path = self.root.join("final-artifact");
        tokio::fs::write(&path, content).await?;

        // Also save the hash
        let hash = sha256_hex(content.as_bytes());
        tokio::fs::write(self.root.join("final-artifact.sha256"), &hash).await?;

        Ok(path)
    }

    /// Save the run summary.
    pub async fn save_summary(&self, summary: &impl Serialize) -> Result<()> {
        let path = self.root.join("summary.json");
        let json = serde_json::to_string_pretty(summary)?;
        tokio::fs::write(&path, &json).await?;
        Ok(())
    }

    /// Save arbitrary JSON to an attempt directory.
    pub async fn save_attempt_file(
        &self,
        attempt: u8,
        filename: &str,
        content: &impl Serialize,
    ) -> Result<()> {
        let dir = self.create_attempt(attempt).await?;
        let path = dir.join(filename);
        let json = serde_json::to_string_pretty(content)?;
        tokio::fs::write(&path, &json).await?;
        Ok(())
    }

    /// Save arbitrary string content to an attempt directory.
    pub async fn save_attempt_raw(&self, attempt: u8, filename: &str, content: &str) -> Result<PathBuf> {
        let dir = self.create_attempt(attempt).await?;
        let path = dir.join(filename);
        if let Some(p) = path.parent() {
            tokio::fs::create_dir_all(p).await?;
        }
        tokio::fs::write(&path, content).await?;
        Ok(path)
    }
}

/// Compute SHA-256 hex digest of bytes.
pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}
