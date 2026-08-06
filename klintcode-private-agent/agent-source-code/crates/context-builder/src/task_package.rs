use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Represents a loaded task package directory.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskPackageData {
    pub name: String,
    pub root: PathBuf,
    pub task_content: String,
    pub grammar_example: Option<String>,
    pub value_whitelist: Option<String>,
    pub acceptance_spec: Option<serde_json::Value>,
    pub workspace_manifest: Option<WorkspaceManifest>,
    pub tool_policy: Option<ToolPolicy>,
    /// Optional modeling skill content injected into generation/repair prompts.
    /// Loaded from a SKILL.md file; only the `model_generation` phase section
    /// is extracted and included. Automatically absent from post-modeling phases.
    #[serde(default)]
    pub modeling_skill: Option<String>,
}

/// Workspace manifest: controls which files the agent can access.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceManifest {
    #[serde(default)]
    pub readable: Vec<String>,
    #[serde(default)]
    pub writable: Vec<String>,
    #[serde(default)]
    pub denied: Vec<String>,
    #[serde(default = "default_max_single_file_bytes")]
    pub max_single_file_bytes: u64,
    #[serde(default = "default_max_total_read_bytes")]
    pub max_total_read_bytes: u64,
    #[serde(default)]
    pub recursive_discovery: bool,
}

fn default_max_single_file_bytes() -> u64 {
    180_000
}
fn default_max_total_read_bytes() -> u64 {
    500_000
}

/// Tool policy: controls which commands can be executed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolPolicy {
    #[serde(default)]
    pub allowed_commands: Vec<CommandTemplate>,
    #[serde(default = "default_false")]
    pub allow_shell: bool,
    #[serde(default = "default_false")]
    pub allow_network: bool,
}

fn default_false() -> bool {
    false
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandTemplate {
    pub template: String,
    pub description: String,
    #[serde(default)]
    pub allowed_args: Vec<String>,
}

impl TaskPackageData {
    /// Build an in-memory task from text entered in an interactive client.
    ///
    /// Automatically loads the canonical grammar example so that inline tasks
    /// get the same KSML structure guidance as file-based task packages.
    pub fn from_prompt(
        name: impl Into<String>,
        prompt: impl Into<String>,
        workspace_root: PathBuf,
    ) -> Self {
        Self {
            name: name.into(),
            root: workspace_root,
            task_content: prompt.into(),
            grammar_example: None,
            value_whitelist: None,
            acceptance_spec: None,
            workspace_manifest: None,
            tool_policy: None,
            modeling_skill: None,
        }
    }

    /// Load a task package from a directory.
    pub fn load(dir: &Path) -> Result<Self> {
        let name = dir
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "unknown".to_string());

        let task_file = dir.join("task.md");
        let task_content = std::fs::read_to_string(&task_file)
            .with_context(|| format!("Failed to read task.md from {}", dir.display()))?;

        let grammar_example = read_optional(dir, "grammar-example.xml")?;
        let value_whitelist = read_optional(dir, "value-whitelist.txt")?;

        let acceptance_spec = if dir.join("acceptance.json").exists() {
            let content = std::fs::read_to_string(dir.join("acceptance.json"))?;
            Some(serde_json::from_str(&content)?)
        } else {
            None
        };

        let workspace_manifest = if dir.join("workspace-manifest.toml").exists() {
            let content = std::fs::read_to_string(dir.join("workspace-manifest.toml"))?;
            Some(toml::from_str(&content)?)
        } else {
            None
        };

        let tool_policy = if dir.join("tool-policy.toml").exists() {
            let content = std::fs::read_to_string(dir.join("tool-policy.toml"))?;
            Some(toml::from_str(&content)?)
        } else {
            None
        };

        // Load modeling skill from skill.md in the task package directory
        let modeling_skill = read_optional(dir, "skill.md")?
            .and_then(|content| extract_phase_content(&content, "model_generation"));

        Ok(Self {
            name,
            root: dir.to_path_buf(),
            task_content,
            grammar_example,
            value_whitelist,
            acceptance_spec,
            workspace_manifest,
            tool_policy,
            modeling_skill,
        })
    }

    /// Create a minimal task package from inline text (typed in TUI).
    pub fn from_inline_text(text: &str) -> Self {
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        Self {
            name: "inline-task".to_string(),
            root: cwd,
            task_content: text.to_string(),
            grammar_example: None,
            value_whitelist: None,
            acceptance_spec: None,
            workspace_manifest: None,
            tool_policy: None,
            modeling_skill: None,
        }
    }

    /// List all files present in this task package
    pub fn files(&self) -> Vec<PathBuf> {
        let mut files = vec![self.root.join("task.md")];
        if self.grammar_example.is_some() {
            files.push(self.root.join("grammar-example.xml"));
        }
        if self.value_whitelist.is_some() {
            files.push(self.root.join("value-whitelist.txt"));
        }
        if self.acceptance_spec.is_some() {
            files.push(self.root.join("acceptance.json"));
        }
        if self.workspace_manifest.is_some() {
            files.push(self.root.join("workspace-manifest.toml"));
        }
        if self.tool_policy.is_some() {
            files.push(self.root.join("tool-policy.toml"));
        }
        files
    }
}

fn read_optional(dir: &Path, filename: &str) -> Result<Option<String>> {
    let path = dir.join(filename);
    if path.exists() {
        Ok(Some(std::fs::read_to_string(&path)?))
    } else {
        Ok(None)
    }
}

/// Extract content from a `<!-- phase:NAME -->...<!-- /phase:NAME -->` block
/// in a SKILL.md file. Returns the inner content if found.
fn extract_phase_content(content: &str, phase_name: &str) -> Option<String> {
    let start_tag = format!("<!-- phase:{} -->", phase_name);
    let end_tag = format!("<!-- /phase:{} -->", phase_name);

    let start = content.find(&start_tag)?;
    let end = content.find(&end_tag)?;

    if end <= start {
        return None;
    }

    let inner = &content[start + start_tag.len()..end];
    let trimmed = inner.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

impl TaskPackageData {
    /// Load a modeling skill from an external SKILL.md file (e.g., from
    /// teaql-agent-kit). Extracts only the `model_generation` phase section.
    pub fn load_modeling_skill_from(&mut self, skill_path: &Path) -> Result<()> {
        if skill_path.exists() {
            let content = std::fs::read_to_string(skill_path)
                .with_context(|| format!("Failed to read skill file: {}", skill_path.display()))?;
            self.modeling_skill = extract_phase_content(&content, "model_generation");
            if self.modeling_skill.is_some() {
                tracing::info!(path = %skill_path.display(), "Loaded modeling skill");
            }
        }
        Ok(())
    }
}
