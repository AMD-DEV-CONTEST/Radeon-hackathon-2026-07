use agent_core::agent_loop::ToolExecutor;
use agent_core::error::AgentError;
use std::future::Future;

pub struct StandardToolExecutor;

impl ToolExecutor for StandardToolExecutor {
    async fn execute(&self, name: &str, arguments: &str) -> Result<String, AgentError> {
        match name {
            "read_file" => {
                if let Ok(args) = serde_json::from_str::<serde_json::Value>(arguments) {
                    if let Some(path) = args.get("path").and_then(|v| v.as_str()) {
                        match std::fs::read_to_string(path) {
                            Ok(content) => {
                                let start_line = args.get("start_line").and_then(|v| v.as_u64()).unwrap_or(1) as usize;
                                // 默认限制每次最多读 500 行，防止没传 end_line 导致输出过大
                                let default_end = start_line + 500;
                                let end_line = args.get("end_line").and_then(|v| v.as_u64()).unwrap_or(default_end as u64) as usize;
                                
                                let lines: Vec<&str> = content.lines().collect();
                                let total_lines = lines.len();
                                
                                let start_idx = start_line.saturating_sub(1).min(total_lines);
                                let end_idx = end_line.min(total_lines).max(start_idx);
                                
                                let mut output = format!("File: {} (Lines {}-{}/{}):\n", path, start_idx + 1, end_idx, total_lines);
                                for (i, line) in lines[start_idx..end_idx].iter().enumerate() {
                                    output.push_str(&format!("{:5} | {}\n", start_idx + i + 1, line));
                                }
                                
                                if end_idx < total_lines {
                                    output.push_str(&format!("\n... (File continues. Use start_line={} to read more)", end_idx + 1));
                                }
                                Ok(output)
                            }
                            Err(e) => Err(AgentError::InfrastructureError { detail: e.to_string() })
                        }
                    } else {
                        Ok("Error: missing 'path' argument".to_string())
                    }
                } else {
                    Ok("Error: invalid json arguments".to_string())
                }
            }
            "write_file" => {
                if let Ok(args) = serde_json::from_str::<serde_json::Value>(arguments) {
                    if let (Some(path), Some(content)) = (args.get("path").and_then(|v| v.as_str()), args.get("content").and_then(|v| v.as_str())) {
                        match std::fs::write(path, content) {
                            Ok(_) => Ok(format!("Successfully wrote to {}", path)),
                            Err(e) => Ok(format!("Error writing file: {}", e)),
                        }
                    } else {
                        Ok("Error: missing 'path' or 'content' argument".to_string())
                    }
                } else {
                    Ok("Error: invalid json arguments".to_string())
                }
            }
            "run_command" => {
                if let Ok(args) = serde_json::from_str::<serde_json::Value>(arguments) {
                    if let Some(cmd) = args.get("command").and_then(|v| v.as_str()) {
                        match std::process::Command::new("sh").arg("-c").arg(cmd).output() {
                            Ok(output) => {
                                let stdout = String::from_utf8_lossy(&output.stdout);
                                let stderr = String::from_utf8_lossy(&output.stderr);
                                Ok(format!("Exit Status: {}\nSTDOUT:\n{}\nSTDERR:\n{}", output.status, stdout, stderr))
                            }
                            Err(e) => Ok(format!("Error running command: {}", e)),
                        }
                    } else {
                        Ok("Error: missing 'command' argument".to_string())
                    }
                } else {
                    Ok("Error: invalid json arguments".to_string())
                }
            }
            "finish_task" => {
                Ok("Task recorded as finished.".to_string())
            }
            _ => Ok(format!("Error: unknown tool {}", name)),
        }
    }
}
