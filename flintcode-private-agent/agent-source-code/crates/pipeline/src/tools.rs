//! Sandboxed tool execution for the agentic build loop.
//!
//! Provides tools that let the LLM inspect, compile, and fix code
//! within a restricted project directory.

use serde_json::json;
use std::path::{Path, PathBuf};
use tokio::process::Command;
use tracing::{info, warn};

use model_vllm::chat::{Function, Tool};

/// Maximum output length per tool result (chars) to avoid context overflow
const MAX_OUTPUT_LEN: usize = 4000;

/// Get the tool definitions for the agentic build loop
pub fn build_tool_definitions() -> Vec<Tool> {
    vec![
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "run_command".to_string(),
                description: Some("Execute a shell command in the project directory. Use for compiling, testing, or inspecting the project.".to_string()),
                parameters: Some(json!({
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute"
                        }
                    },
                    "required": ["command"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "read_file".to_string(),
                description: Some("Read the contents of a file in the project.".to_string()),
                parameters: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file, relative to the project root"
                        }
                    },
                    "required": ["path"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "write_file".to_string(),
                description: Some("Write content to a file. Creates parent directories if needed.".to_string()),
                parameters: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file, relative to the project root"
                        },
                        "content": {
                            "type": "string",
                            "description": "The complete content to write to the file"
                        }
                    },
                    "required": ["path", "content"]
                })),
            },
        },
        Tool {
            r#type: "function".to_string(),
            function: Function {
                name: "list_directory".to_string(),
                description: Some("List files and directories at a path.".to_string()),
                parameters: Some(json!({
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path relative to project root. Use '.' for root."
                        }
                    },
                    "required": ["path"]
                })),
            },
        },
    ]
}

/// Execute a tool call in a sandboxed directory.
///
/// All file operations are restricted to the sandbox directory.
/// Returns a human-readable result string for the LLM.
pub async fn execute_tool(tool_name: &str, arguments: &str, sandbox_dir: &Path) -> String {
    let args: serde_json::Value = match serde_json::from_str(arguments) {
        Ok(v) => v,
        Err(e) => return format!("Error parsing arguments: {}", e),
    };

    match tool_name {
        "run_command" => execute_run_command(&args, sandbox_dir).await,
        "read_file" => execute_read_file(&args, sandbox_dir),
        "write_file" => execute_write_file(&args, sandbox_dir),
        "list_directory" => execute_list_directory(&args, sandbox_dir),
        _ => format!("Unknown tool: {}", tool_name),
    }
}

async fn execute_run_command(args: &serde_json::Value, sandbox_dir: &Path) -> String {
    let command = args["command"].as_str().unwrap_or("");
    if command.is_empty() {
        return "Error: empty command".to_string();
    }

    info!(command, dir = %sandbox_dir.display(), "Agent executing command");

    let result = Command::new("bash")
        .args(["-c", command])
        .current_dir(sandbox_dir)
        .env("PAGER", "cat")
        .output()
        .await;

    match result {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let stderr = String::from_utf8_lossy(&output.stderr);
            let status = output.status.code().unwrap_or(-1);

            let stdout_trunc = truncate_output(&stdout, MAX_OUTPUT_LEN);
            let stderr_trunc = truncate_output(&stderr, MAX_OUTPUT_LEN);

            format!(
                "Exit code: {}\nStdout:\n{}\nStderr:\n{}",
                status, stdout_trunc, stderr_trunc
            )
        }
        Err(e) => format!("Error executing command: {}", e),
    }
}

fn execute_read_file(args: &serde_json::Value, sandbox_dir: &Path) -> String {
    let path = args["path"].as_str().unwrap_or("");
    if path.is_empty() {
        return "Error: empty path".to_string();
    }

    let full_path = resolve_path(sandbox_dir, path);
    if !is_within_sandbox(&full_path, sandbox_dir) {
        return "Error: path is outside the project directory".to_string();
    }

    match std::fs::read_to_string(&full_path) {
        Ok(content) => truncate_output(&content, MAX_OUTPUT_LEN * 2),
        Err(e) => format!("Error reading file '{}': {}", path, e),
    }
}

fn execute_write_file(args: &serde_json::Value, sandbox_dir: &Path) -> String {
    let path = args["path"].as_str().unwrap_or("");
    let content = args["content"].as_str().unwrap_or("");

    if path.is_empty() {
        return "Error: empty path".to_string();
    }

    let full_path = resolve_path(sandbox_dir, path);
    if !is_within_sandbox(&full_path, sandbox_dir) {
        return "Error: path is outside the project directory".to_string();
    }

    // Create parent directories if needed
    if let Some(parent) = full_path.parent() {
        if let Err(e) = std::fs::create_dir_all(parent) {
            return format!("Error creating directories: {}", e);
        }
    }

    match std::fs::write(&full_path, content) {
        Ok(_) => {
            info!(path, bytes = content.len(), "Agent wrote file");
            format!("Successfully wrote {} bytes to {}", content.len(), path)
        }
        Err(e) => format!("Error writing file '{}': {}", path, e),
    }
}

fn execute_list_directory(args: &serde_json::Value, sandbox_dir: &Path) -> String {
    let path = args["path"].as_str().unwrap_or(".");
    let full_path = resolve_path(sandbox_dir, path);

    if !is_within_sandbox(&full_path, sandbox_dir) {
        return "Error: path is outside the project directory".to_string();
    }

    match std::fs::read_dir(&full_path) {
        Ok(entries) => {
            let mut listing = Vec::new();
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                let kind = entry
                    .file_type()
                    .map(|t| if t.is_dir() { "dir" } else { "file" })
                    .unwrap_or("?");
                listing.push(format!("  {} ({})", name, kind));
            }
            listing.sort();
            if listing.is_empty() {
                "Directory is empty".to_string()
            } else {
                listing.join("\n")
            }
        }
        Err(e) => format!("Error listing directory '{}': {}", path, e),
    }
}

/// Resolve a relative path against the sandbox directory
fn resolve_path(sandbox: &Path, relative: &str) -> PathBuf {
    let path = Path::new(relative);
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        sandbox.join(path)
    }
}

/// Check if a path is within the sandbox directory (prevents directory traversal)
fn is_within_sandbox(path: &Path, sandbox: &Path) -> bool {
    // For existing paths, use canonicalize
    if let (Ok(p), Ok(s)) = (path.canonicalize(), sandbox.canonicalize()) {
        return p.starts_with(s);
    }
    // For non-existent paths (e.g. write_file targets), check the parent
    if let Some(parent) = path.parent() {
        if let (Ok(p), Ok(s)) = (parent.canonicalize(), sandbox.canonicalize()) {
            return p.starts_with(s);
        }
    }
    // If we can't verify, reject
    warn!(path = %path.display(), "Cannot verify sandbox containment");
    false
}

/// Truncate output to avoid blowing the context window
fn truncate_output(text: &str, max_len: usize) -> String {
    if text.len() > max_len {
        let mut boundary = max_len;
        while boundary > 0 && !text.is_char_boundary(boundary) {
            boundary -= 1;
        }
        format!(
            "{}...\n[truncated, {} total bytes]",
            &text[..boundary],
            text.len()
        )
    } else {
        text.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncation_respects_utf8_boundaries() {
        let text = "你".repeat(2_000);
        let truncated = truncate_output(&text, MAX_OUTPUT_LEN);
        assert!(truncated.contains("[truncated"));
    }
}
