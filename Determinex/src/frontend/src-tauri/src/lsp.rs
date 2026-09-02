use serde::{Deserialize, Serialize};
use std::process::Command;
use std::fs;
use std::path::Path;
use crate::win_process::HideConsoleExt;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LspDiagnostic {
    pub line: u32,
    pub column: u32,
    pub severity: String, // "error" | "warning" | "info"
    pub message: String,
    /// Was missing entirely -- cargo's own JSON output has span["file_name"],
    /// but it was never read into this struct, so every diagnostic anywhere in
    /// the frontend rendered "unknown file" even for a real compiler error.
    pub file: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LspSymbol {
    pub name: String,
    pub kind: String, // "class" | "method" | "function" | "variable"
    pub line: u32,
}

#[tauri::command]
pub fn get_lsp_diagnostics(file_name: String, workspace_path: Option<String>) -> Result<Vec<LspDiagnostic>, String> {
    let mut diagnostics = Vec::new();

    // For Rust files, we can shell out to cargo check --message-format=json. This USED to run
    // with no current_dir set at all -- meaning it checked whatever the process's ambient cwd
    // happened to be (the app's own install dir when packaged), never the user's actual open
    // workspace. Now scoped to workspace_path (or its src-tauri/ subdir), same Cargo.toml
    // detection as run_project_audit; if neither is a real Cargo project, this returns empty
    // rather than fabricating results from the wrong directory.
    // An empty file_name means "whole project" (ProblemsPanel's use case); a real filename
    // filters to just that file's diagnostics (EditorPanel's per-file use case).
    let whole_project = file_name.is_empty();
    if whole_project || file_name.ends_with(".rs") {
        let cargo_dir = workspace_path.as_deref().and_then(|ws| {
            let root = Path::new(ws);
            if root.join("Cargo.toml").is_file() {
                Some(root.to_path_buf())
            } else if root.join("src-tauri").join("Cargo.toml").is_file() {
                Some(root.join("src-tauri"))
            } else if root.join("frontend").join("src-tauri").join("Cargo.toml").is_file() {
                // This exact repo's shape: Cargo.toml lives two levels down. Same
                // gap independently found and fixed in project_audit.rs's audit run.
                Some(root.join("frontend").join("src-tauri"))
            } else {
                None
            }
        });
        let Some(cargo_dir) = cargo_dir else {
            return Ok(diagnostics); // not a Rust project in this workspace -- honestly empty
        };
        let mut cmd = Command::new("cargo");
        cmd.hide_console();
        cmd.args(["check", "--message-format=json"]).current_dir(&cargo_dir);
        // Bounded for the same reason run_project_audit's cargo check is bounded:
        // this now actually runs (the path-detection fix above means cargo_dir is
        // no longer always None for this repo), and an unbounded cold build could
        // block this panel's poll cycle for minutes.
        let output = crate::project_audit::run_with_timeout(cmd, std::time::Duration::from_secs(90));

        if let Ok(output) = output {
            let stdout = String::from_utf8_lossy(&output.stdout);
            for line in stdout.lines() {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(line) {
                    if json["reason"] == "compiler-message" {
                        let msg = &json["message"];
                        let severity_raw = msg["level"].as_str().unwrap_or("info");
                        let severity = match severity_raw {
                            "error" => "error",
                            "warning" => "warning",
                            _ => "info",
                        };

                        let text = msg["message"].as_str().unwrap_or("").to_string();

                        if let Some(spans) = msg["spans"].as_array() {
                            for span in spans {
                                if span["is_primary"].as_bool().unwrap_or(false) {
                                    let span_file = span["file_name"].as_str().unwrap_or("");
                                    if whole_project || span_file.ends_with(&file_name) {
                                        diagnostics.push(LspDiagnostic {
                                            line: span["line_start"].as_u64().unwrap_or(1) as u32,
                                            column: span["column_start"].as_u64().unwrap_or(1) as u32,
                                            severity: severity.to_string(),
                                            message: text.clone(),
                                            file: span_file.to_string(),
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    } else if file_name.ends_with(".ts") || file_name.ends_with(".tsx") {
        // Fallback for JS/TS: we could run tsc or eslint, but that takes a while.
        // For now, return an empty array rather than failing.
    }

    Ok(diagnostics)
}

#[tauri::command]
pub fn get_lsp_symbols(file_name: String) -> Result<Vec<LspSymbol>, String> {
    let mut symbols = Vec::new();

    // Fallback: read file and do rudimentary regex matching
    let path = Path::new(&file_name);
    let abs_path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        // Assume workspace root
        std::env::current_dir().unwrap_or_default().join(path)
    };

    if let Ok(content) = fs::read_to_string(&abs_path) {
        let mut line_num = 1;
        for line in content.lines() {
            let t = line.trim();
            // Very naive heuristics for demo purposes.
            // A real Language Server Protocol integration would use an LSP client.
            if t.starts_with("fn ") || t.starts_with("pub fn ") {
                if let Some(name) = t.split("fn ").nth(1).and_then(|s| s.split('(').next()) {
                    symbols.push(LspSymbol {
                        name: name.trim().to_string(),
                        kind: "function".to_string(),
                        line: line_num,
                    });
                }
            } else if t.starts_with("class ") || t.starts_with("export class ") {
                if let Some(name) = t.split("class ").nth(1).and_then(|s| s.split_whitespace().next()) {
                    symbols.push(LspSymbol {
                        name: name.trim().to_string(),
                        kind: "class".to_string(),
                        line: line_num,
                    });
                }
            } else if t.contains("struct ") {
                if let Some(name) = t.split("struct ").nth(1).and_then(|s| s.split_whitespace().next()) {
                    symbols.push(LspSymbol {
                        name: name.trim().to_string(),
                        kind: "class".to_string(), // map struct to class for the UI
                        line: line_num,
                    });
                }
            }
            line_num += 1;
        }
    }

    Ok(symbols)
}
