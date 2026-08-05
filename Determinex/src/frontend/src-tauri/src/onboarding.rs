use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceAnalysis {
    pub has_package_json: bool,
    pub has_cargo_toml: bool,
    pub has_requirements_txt: bool,
    pub inferred_stack: Vec<String>,
    pub recommended_action: String,
    pub build_command: Option<String>,
    /// The exact command "Execute Action" runs -- always kept consistent
    /// with `recommended_action` (e.g. "npm install" when the recommendation
    /// is to install dependencies, not the build command).
    pub action_command: Option<String>,
    /// Absolute directory `action_command` must run from. In a monorepo like
    /// this one, package.json lives under `frontend/`, not the workspace
    /// root -- passing the workspace root as cwd made every "Execute Action"
    /// click fail with npm ENOENT (found live 2026-07-19, first-run bug: the
    /// very first button a new user clicks). Always set alongside
    /// action_command so the frontend never has to guess the right cwd.
    pub action_cwd: Option<String>,
}

#[tauri::command]
pub async fn analyze_workspace(workspace: String) -> Result<WorkspaceAnalysis, String> {
    // Basic heuristics
    let root = Path::new(&workspace);
    let mut inferred_stack = Vec::new();
    let mut recommended_action = "Run Audit".to_string();
    let mut build_command = None;
    let mut action_command = None;
    let mut action_cwd = None;

    let package_json_at_root = root.join("package.json").exists();
    let package_json_dir = if package_json_at_root {
        Some(root.to_path_buf())
    } else if root.join("frontend/package.json").exists() {
        Some(root.join("frontend"))
    } else {
        None
    };
    let has_package_json = package_json_dir.is_some();

    let cargo_toml_at_root = root.join("Cargo.toml").exists();
    let cargo_toml_dir = if cargo_toml_at_root {
        Some(root.to_path_buf())
    } else if root.join("frontend/src-tauri/Cargo.toml").exists() {
        Some(root.join("frontend/src-tauri"))
    } else {
        None
    };
    let has_cargo_toml = cargo_toml_dir.is_some();

    let has_requirements_txt = root.join("requirements.txt").exists() || root.join("pyproject.toml").exists();

    if let Some(dir) = &package_json_dir {
        inferred_stack.push("Node.js".to_string());
        build_command = Some(("npm run build".to_string(), dir.clone()));
    }
    if let Some(dir) = &cargo_toml_dir {
        inferred_stack.push("Rust (Tauri)".to_string());
        if build_command.is_none() {
            build_command = Some(("cargo build".to_string(), dir.clone()));
        }
    }
    if has_requirements_txt {
        inferred_stack.push("Python".to_string());
    }

    let node_modules_present = package_json_dir
        .as_ref()
        .is_some_and(|dir| dir.join("node_modules").exists());

    if inferred_stack.is_empty() {
        inferred_stack.push("Unknown".to_string());
        recommended_action = "Initialize Project".to_string();
    } else if has_package_json && !node_modules_present {
        recommended_action = "Install Dependencies (npm install)".to_string();
        action_command = Some("npm install".to_string());
        action_cwd = package_json_dir.as_ref().map(|d| d.to_string_lossy().to_string());
    } else if let Some((cmd, dir)) = &build_command {
        action_command = Some(cmd.clone());
        action_cwd = Some(dir.to_string_lossy().to_string());
    }

    Ok(WorkspaceAnalysis {
        has_package_json,
        has_cargo_toml,
        has_requirements_txt,
        inferred_stack,
        recommended_action,
        build_command: build_command.map(|(cmd, _)| cmd),
        action_command,
        action_cwd,
    })
}
