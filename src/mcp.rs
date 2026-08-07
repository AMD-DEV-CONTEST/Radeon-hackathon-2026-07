//! MCP (Model Context Protocol) tool definitions for cesarops-inference.
//!
//! Exposes hardware audit, model info, and inference control as MCP tools.
//! Any MCP client (Kiro, Claude Desktop, forge-v2) can call these.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::{BufRead, Write};
use tracing::info;

use crate::hardware;
use crate::loader;

/// MCP tool handler — routes JSON-RPC calls to the right function.
pub fn handle_tool_call(tool_name: &str, arguments: &Value) -> Value {
    match tool_name {
        "audit_hardware" => tool_audit_hardware(),
        "model_info" => tool_model_info(arguments),
        "check_gpu_memory" => tool_check_gpu_memory(),
        "estimate_model_fit" => tool_estimate_model_fit(arguments),
        "health" => tool_health(),
        "read_file" => tool_read_file(arguments),
        "write_file" => tool_write_file(arguments),
        "list_files" => tool_list_files(arguments),
        "cargo_check" => tool_cargo_check(arguments),
        "run_command" => tool_run_command(arguments),
        _ => json!({"error": format!("Unknown tool: {}", tool_name)}),
    }
}

/// Returns the full list of available MCP tools.
pub fn tool_list() -> Value {
    json!({
        "tools": [
            {
                "name": "audit_hardware",
                "description": "Audit the system hardware: GPUs, CPUs, NUMA topology, RAM. Returns an IronProfile with all detected devices and their capabilities.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "model_info",
                "description": "Parse a GGUF model file header and return metadata: layer count, expert count, hidden dim, vocab size, quantization type.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the GGUF model file"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "check_gpu_memory",
                "description": "Check current GPU memory usage via nvidia-smi. Returns used/total for each GPU.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "estimate_model_fit",
                "description": "Estimate whether a model will fit in available GPU memory. Returns fit analysis with recommended sharding strategy.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model_size_gb": {
                            "type": "number",
                            "description": "Model size in GB"
                        },
                        "context_size": {
                            "type": "integer",
                            "description": "Desired context window size in tokens"
                        }
                    },
                    "required": ["model_size_gb"]
                }
            },
            {
                "name": "health",
                "description": "Check inference engine health: GPU temps, memory, model loaded status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "read_file",
                "description": "Read a file from the project. Returns the file content as text. Truncates at 8000 chars.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root (e.g. cesarops-inference/src/lib.rs)"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "Write content to a file. Creates parent directories if needed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from project root"
                        },
                        "content": {
                            "type": "string",
                            "description": "File content to write"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "list_files",
                "description": "List files in a directory. Returns file names and sizes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative directory path from project root"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "cargo_check",
                "description": "Run cargo check on a crate directory. Returns compiler errors or OK.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "dir": {
                            "type": "string",
                            "description": "Relative path to the crate directory (e.g. cesarops-inference)"
                        }
                    },
                    "required": ["dir"]
                }
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the project root. Blocked: rm -rf, dd, mkfs. Truncates output at 4000 chars.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "Shell command to execute"
                        }
                    },
                    "required": ["cmd"]
                }
            }
        ]
    })
}

// --- Tool implementations ---

fn tool_audit_hardware() -> Value {
    let profile = hardware::audit_system();
    json!({
        "gpus": profile.gpu_nodes.iter().map(|g| json!({
            "index": g.index,
            "name": g.name,
            "vram_mb": g.vram_mb,
            "supports_f16": g.supports_f16,
        })).collect::<Vec<_>>(),
        "cpus": profile.cpu_nodes.iter().map(|c| json!({
            "socket_id": c.socket_id,
            "core_count": c.core_count,
            "has_avx512": c.has_avx512,
        })).collect::<Vec<_>>(),
        "total_vram_mb": profile.total_vram_mb,
        "total_host_ram_mb": profile.total_host_ram_mb,
        "numa_nodes": profile.numa_node_count,
    })
}

fn tool_model_info(args: &Value) -> Value {
    let path = match args.get("path").and_then(|p| p.as_str()) {
        Some(p) => std::path::Path::new(p),
        None => return json!({"error": "path argument required"}),
    };

    let profile = hardware::audit_system();
    match loader::load(path, &profile) {
        Ok(weights) => json!({
            "n_layers": weights.n_layers,
            "n_experts": weights.n_experts,
            "hidden_dim": weights.hidden_dim,
            "n_heads": weights.n_heads,
            "n_kv_heads": weights.n_kv_heads,
            "vocab_size": weights.vocab_size,
            "n_tensors": weights.tensors.len(),
        }),
        Err(e) => json!({"error": format!("Failed to load model: {}", e)}),
    }
}

fn tool_check_gpu_memory() -> Value {
    let output = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=index,name,memory.used,memory.total,temperature.gpu",
               "--format=csv,noheader,nounits"])
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let gpus: Vec<Value> = stdout.lines().filter_map(|line| {
                let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
                if parts.len() >= 5 {
                    Some(json!({
                        "index": parts[0],
                        "name": parts[1],
                        "memory_used_mb": parts[2].parse::<u64>().unwrap_or(0),
                        "memory_total_mb": parts[3].parse::<u64>().unwrap_or(0),
                        "temperature_c": parts[4].parse::<u32>().unwrap_or(0),
                    }))
                } else {
                    None
                }
            }).collect();
            json!({"gpus": gpus})
        }
        _ => json!({"error": "nvidia-smi not available"}),
    }
}

fn tool_estimate_model_fit(args: &Value) -> Value {
    let model_size_gb = args.get("model_size_gb").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let context_size = args.get("context_size").and_then(|v| v.as_u64()).unwrap_or(8192);

    let profile = hardware::audit_system();
    let total_vram_gb = profile.total_vram_mb as f64 / 1024.0;

    // KV cache estimate: 2 * n_layers * 2 * hidden_dim * context_size * 2 bytes (f16)
    // Rough estimate: ~2GB per 8K context for a 14B model, ~6GB for 35B
    let kv_estimate_gb = (model_size_gb / 5.0) * (context_size as f64 / 8192.0);

    let total_needed = model_size_gb + kv_estimate_gb;
    let fits = total_needed <= total_vram_gb;

    let strategy = if fits {
        if profile.gpu_nodes.len() > 1 {
            "tensor_parallel_across_gpus"
        } else {
            "single_gpu"
        }
    } else if total_needed <= total_vram_gb + (profile.total_host_ram_mb as f64 / 1024.0) {
        "gpu_with_cpu_offload"
    } else {
        "requires_quantization"
    };

    json!({
        "model_size_gb": model_size_gb,
        "kv_cache_estimate_gb": kv_estimate_gb,
        "total_needed_gb": total_needed,
        "total_vram_available_gb": total_vram_gb,
        "total_ram_available_gb": profile.total_host_ram_mb as f64 / 1024.0,
        "fits_in_vram": fits,
        "recommended_strategy": strategy,
        "gpu_count": profile.gpu_nodes.len(),
    })
}

fn tool_health() -> Value {
    let profile = hardware::audit_system();
    json!({
        "status": "ok",
        "service": "cesarops-inference",
        "gpus_detected": profile.gpu_nodes.len(),
        "total_vram_mb": profile.total_vram_mb,
        "total_ram_mb": profile.total_host_ram_mb,
        "numa_nodes": profile.numa_node_count,
    })
}

const PROJECT_ROOT: &str = "/codebase/wreckhunter2000-1";

fn tool_read_file(args: &Value) -> Value {
    let path = match args.get("path").and_then(|p| p.as_str()) {
        Some(p) => p,
        None => return json!({"error": "path argument required"}),
    };

    let full_path = std::path::Path::new(PROJECT_ROOT).join(path);
    match std::fs::read_to_string(&full_path) {
        Ok(content) => {
            if content.len() > 8000 {
                json!({
                    "content": &content[..8000],
                    "truncated": true,
                    "total_bytes": content.len()
                })
            } else {
                json!({"content": content, "truncated": false, "total_bytes": content.len()})
            }
        }
        Err(e) => json!({"error": format!("Failed to read {}: {}", path, e)}),
    }
}

fn tool_write_file(args: &Value) -> Value {
    let path = match args.get("path").and_then(|p| p.as_str()) {
        Some(p) => p,
        None => return json!({"error": "path argument required"}),
    };
    let content = match args.get("content").and_then(|c| c.as_str()) {
        Some(c) => c,
        None => return json!({"error": "content argument required"}),
    };

    let full_path = std::path::Path::new(PROJECT_ROOT).join(path);

    // Create parent dirs
    if let Some(parent) = full_path.parent() {
        if let Err(e) = std::fs::create_dir_all(parent) {
            return json!({"error": format!("Failed to create dirs: {}", e)});
        }
    }

    match std::fs::write(&full_path, content) {
        Ok(_) => json!({"written": path, "bytes": content.len()}),
        Err(e) => json!({"error": format!("Failed to write {}: {}", path, e)}),
    }
}

fn tool_list_files(args: &Value) -> Value {
    let path = match args.get("path").and_then(|p| p.as_str()) {
        Some(p) => p,
        None => return json!({"error": "path argument required"}),
    };

    let full_path = std::path::Path::new(PROJECT_ROOT).join(path);
    match std::fs::read_dir(&full_path) {
        Ok(entries) => {
            let files: Vec<Value> = entries.filter_map(|e| {
                let entry = e.ok()?;
                let meta = entry.metadata().ok()?;
                Some(json!({
                    "name": entry.file_name().to_string_lossy(),
                    "is_dir": meta.is_dir(),
                    "size": meta.len(),
                }))
            }).collect();
            json!({"path": path, "entries": files})
        }
        Err(e) => json!({"error": format!("Failed to list {}: {}", path, e)}),
    }
}

fn tool_cargo_check(args: &Value) -> Value {
    let dir = match args.get("dir").and_then(|d| d.as_str()) {
        Some(d) => d,
        None => return json!({"error": "dir argument required"}),
    };

    let full_dir = std::path::Path::new(PROJECT_ROOT).join(dir);
    let output = std::process::Command::new("cargo")
        .args(["check", "--message-format=short"])
        .current_dir(&full_dir)
        .env("PATH", format!("/home/cesarops/.cargo/bin:{}", std::env::var("PATH").unwrap_or_default()))
        .output();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            if out.status.success() {
                json!({"status": "ok", "message": "cargo check passed"})
            } else {
                let errors: String = stderr.lines()
                    .filter(|l| l.contains("error"))
                    .take(10)
                    .collect::<Vec<_>>()
                    .join("\n");
                json!({"status": "error", "errors": errors})
            }
        }
        Err(e) => json!({"error": format!("Failed to run cargo: {}", e)}),
    }
}

fn tool_run_command(args: &Value) -> Value {
    let cmd = match args.get("cmd").and_then(|c| c.as_str()) {
        Some(c) => c,
        None => return json!({"error": "cmd argument required"}),
    };

    // K-line guard
    let blocked = ["rm -rf /", "rm -rf /*", "dd if=", "mkfs", "> /dev/sd"];
    for pattern in &blocked {
        if cmd.contains(pattern) {
            return json!({"error": format!("BLOCKED: dangerous command pattern '{}'", pattern)});
        }
    }

    let output = std::process::Command::new("bash")
        .args(["-c", cmd])
        .current_dir(PROJECT_ROOT)
        .output();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            let mut result = stdout.to_string();
            if !stderr.is_empty() {
                result.push_str("\n[stderr]: ");
                result.push_str(&stderr);
            }
            if result.len() > 4000 {
                result.truncate(4000);
                result.push_str("\n...[truncated]");
            }
            json!({"exit_code": out.status.code(), "output": result})
        }
        Err(e) => json!({"error": format!("Failed to execute: {}", e)}),
    }
}

/// Run the MCP server over stdio (JSON-RPC 2.0).
pub fn serve_mcp_stdio() {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();

    info!("cesarops-inference MCP server ready on stdio");

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };

        if line.trim().is_empty() {
            continue;
        }

        let request: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let _ = writeln!(stdout, "{}", json!({"error": format!("Invalid JSON: {}", e)}));
                continue;
            }
        };

        let method = request["method"].as_str().unwrap_or("");
        let id = &request["id"];
        let params = &request["params"];

        let response = match method {
            "initialize" => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": { "tools": {} },
                    "serverInfo": {
                        "name": "cesarops-inference",
                        "version": "0.1.0"
                    }
                }
            }),
            "tools/list" => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": tool_list()
            }),
            "tools/call" => {
                let tool_name = params["name"].as_str().unwrap_or("");
                let arguments = &params["arguments"];
                let result = handle_tool_call(tool_name, arguments);
                json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "content": [{"type": "text", "text": serde_json::to_string_pretty(&result).unwrap_or_default()}]
                    }
                })
            },
            "notifications/initialized" => continue,
            _ => json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": {"code": -32601, "message": format!("Method not found: {}", method)}
            }),
        };

        let _ = writeln!(stdout, "{}", serde_json::to_string(&response).unwrap_or_default());
        let _ = stdout.flush();
    }
}
