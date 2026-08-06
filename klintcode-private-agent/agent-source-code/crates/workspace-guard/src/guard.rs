use anyhow::Result;
use std::path::{Path, PathBuf};
use thiserror::Error;

use crate::manifest::Manifest;

#[derive(Debug, Error)]
pub enum GuardError {
    #[error("Path escapes workspace root: {path}")]
    EscapesRoot { path: String },
    #[error("Symlink not allowed: {path}")]
    SymlinkRejected { path: String },
    #[error("Path denied by policy: {path}")]
    DeniedByPolicy { path: String },
    #[error("File too large: {size} bytes > limit {limit}")]
    FileTooLarge { size: u64, limit: u64 },
    #[error("Total read limit exceeded: {total} bytes > limit {limit}")]
    TotalReadExceeded { total: u64, limit: u64 },
    #[error("Parent directory missing: {path}")]
    ParentDirMissing { path: String },
}

/// Policy decision record for audit trail
#[derive(Debug, Clone)]
pub struct PolicyDecision {
    pub action: String,
    pub target: String,
    pub allowed: bool,
    pub reason: String,
}

/// Workspace guard enforces file access policies.
pub struct WorkspaceGuard {
    manifest: Manifest,
    canonical_root: PathBuf,
    total_bytes_read: u64,
    decisions: Vec<PolicyDecision>,
}

impl WorkspaceGuard {
    pub fn new(manifest: Manifest) -> Result<Self> {
        let canonical_root = std::fs::canonicalize(&manifest.workspace_root)?;
        Ok(Self {
            manifest,
            canonical_root,
            total_bytes_read: 0,
            decisions: Vec::new(),
        })
    }

    /// Check if a path is within the workspace root.
    pub fn check_read(&mut self, path: &Path) -> std::result::Result<PathBuf, GuardError> {
        let canonical = self.canonicalize_safe(path)?;
        self.check_not_denied(&canonical)?;

        // Check file size
        if let Ok(metadata) = std::fs::metadata(&canonical) {
            let size = metadata.len();
            if size > self.manifest.max_single_file_bytes {
                let err = GuardError::FileTooLarge {
                    size,
                    limit: self.manifest.max_single_file_bytes,
                };
                self.record_decision("read", path, false, &err.to_string());
                return Err(err);
            }
            if self.total_bytes_read + size > self.manifest.max_total_read_bytes {
                let err = GuardError::TotalReadExceeded {
                    total: self.total_bytes_read + size,
                    limit: self.manifest.max_total_read_bytes,
                };
                self.record_decision("read", path, false, &err.to_string());
                return Err(err);
            }
            self.total_bytes_read += size;
        }

        self.record_decision("read", path, true, "allowed");
        Ok(canonical)
    }

    /// Check if a path can be written to.
    pub fn check_write(&mut self, path: &Path) -> std::result::Result<PathBuf, GuardError> {
        // For new files, canonicalize the parent
        let parent = path.parent().unwrap_or(Path::new("."));
        if parent.exists() {
            let canonical_parent = self.canonicalize_safe(parent)?;
            let file_name = path.file_name().unwrap_or_default();
            let canonical = canonical_parent.join(file_name);
            self.check_not_denied(&canonical)?;
            self.record_decision("write", path, true, "allowed");
            Ok(canonical)
        } else {
            let err = GuardError::ParentDirMissing {
                path: parent.display().to_string(),
            };
            self.record_decision("write", path, false, &err.to_string());
            Err(err)
        }
    }

    /// Get all policy decisions for audit
    pub fn decisions(&self) -> &[PolicyDecision] {
        &self.decisions
    }

    fn canonicalize_safe(&self, path: &Path) -> std::result::Result<PathBuf, GuardError> {
        let canonical = std::fs::canonicalize(path).map_err(|_| GuardError::EscapesRoot {
            path: path.display().to_string(),
        })?;

        // Check symlink
        if !self.manifest.follow_symlinks && path.is_symlink() {
            return Err(GuardError::SymlinkRejected {
                path: path.display().to_string(),
            });
        }

        // Check within root
        if !canonical.starts_with(&self.canonical_root) {
            return Err(GuardError::EscapesRoot {
                path: canonical.display().to_string(),
            });
        }

        Ok(canonical)
    }

    fn check_not_denied(&self, path: &Path) -> std::result::Result<(), GuardError> {
        let path_str = path.display().to_string();
        for pattern in &self.manifest.denied {
            if let Ok(glob_pattern) = glob::Pattern::new(pattern) {
                if glob_pattern.matches(&path_str) {
                    return Err(GuardError::DeniedByPolicy { path: path_str });
                }
                // Also check just the filename
                if let Some(name) = path.file_name() {
                    if glob_pattern.matches(&name.to_string_lossy()) {
                        return Err(GuardError::DeniedByPolicy { path: path_str });
                    }
                }
            }
        }
        Ok(())
    }

    fn record_decision(&mut self, action: &str, target: &Path, allowed: bool, reason: &str) {
        self.decisions.push(PolicyDecision {
            action: action.to_string(),
            target: target.display().to_string(),
            allowed,
            reason: reason.to_string(),
        });
    }
}
