use serde::Serialize;
use tokio::process::Command;
use futures;

/// GPU metrics from nvidia-smi.
#[derive(Debug, Clone, Serialize)]
pub struct GpuMetrics {
    pub gpus: Vec<GpuInfo>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GpuInfo {
    pub index: u32,
    pub name: String,
    pub temperature_c: u32,
    pub utilization_pct: u32,
    pub memory_used_mb: u32,
    pub memory_total_mb: u32,
    pub power_draw_w: f32,
}

/// Query GPU metrics via nvidia-smi CSV output.
/// Compatible with NVIDIA driver 580.x on the P100s.
pub async fn query_gpu_metrics() -> GpuMetrics {
    let output = match Command::new("nvidia-smi")
        .args([
            "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .await
    {
        Ok(o) => o,
        Err(e) => {
            return GpuMetrics {
                gpus: Vec::new(),
                error: Some(format!("nvidia-smi failed: {}", e)),
            };
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return GpuMetrics {
            gpus: Vec::new(),
            error: Some(format!("nvidia-smi error: {}", stderr)),
        };
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut gpus = Vec::new();

    for line in stdout.lines() {
        let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
        if parts.len() >= 7 {
            let gpu = GpuInfo {
                index: parts[0].parse().unwrap_or(0),
                name: parts[1].to_string(),
                temperature_c: parts[2].parse().unwrap_or(0),
                utilization_pct: parts[3].parse().unwrap_or(0),
                memory_used_mb: parts[4].parse().unwrap_or(0),
                memory_total_mb: parts[5].parse().unwrap_or(0),
                power_draw_w: parts[6].parse().unwrap_or(0.0),
            };
            gpus.push(gpu);
        }
    }

    GpuMetrics { gpus, error: None }
}

/// Estimate register pressure from WGSL source.
/// Counts var/let declarations as a heuristic for register usage.
/// P100 rule: >32 registers per thread = occupancy drop.
pub fn estimate_register_pressure(wgsl_source: &str) -> RegisterPressureReport {
    let mut var_count: u32 = 0;
    let mut let_count: u32 = 0;

    for line in wgsl_source.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("var ") || trimmed.starts_with("var<") {
            var_count += 1;
        }
        if trimmed.starts_with("let ") {
            let_count += 1;
        }
    }

    let total = var_count + let_count;
    let warning = if total > 20 {
        Some(format!(
            "High register pressure: {} locals (var={}, let={}). Consider splitting into two dispatches.",
            total, var_count, let_count
        ))
    } else {
        None
    };

    RegisterPressureReport {
        var_count,
        let_count,
        total_locals: total,
        exceeds_threshold: total > 20,
        warning,
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct RegisterPressureReport {
    pub var_count: u32,
    pub let_count: u32,
    pub total_locals: u32,
    pub exceeds_threshold: bool,
    pub warning: Option<String>,
}

/// Check if AVX-512 throttling is likely based on active core count.
/// Xeon Silver 4110: 9+ cores with AVX-512 = frequency penalty.
pub fn avx512_throttle_warning(active_avx512_cores: u32) -> Option<String> {
    if active_avx512_cores >= 9 {
        Some(format!(
            "WARNING: {} cores running AVX-512. Xeon 4110 will throttle ALL cores to 1.4GHz. Limit to 8 cores max.",
            active_avx512_cores
        ))
    } else {
        None
    }
}

/// Query GPU metrics via nvidia-smi on a remote node over SSH.
pub async fn query_remote_gpu_metrics(ip: &str, ssh_user: &str) -> Vec<GpuInfo> {
    let output = Command::new("ssh")
        .args([
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=no",
            &format!("{}@{}", ssh_user, ip),
            "nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits 2>/dev/null || echo NO_GPU",
        ])
        .output()
        .await;

    let output = match output {
        Ok(o) => o,
        Err(_) => return vec![],
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    if stdout.trim() == "NO_GPU" || stdout.trim().is_empty() {
        return vec![];
    }

    let mut gpus = Vec::new();
    for line in stdout.lines() {
        let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
        if parts.len() >= 7 {
            gpus.push(GpuInfo {
                index: parts[0].parse().unwrap_or(0),
                name: parts[1].to_string(),
                temperature_c: parts[2].parse().unwrap_or(0),
                utilization_pct: parts[3].parse().unwrap_or(0),
                memory_used_mb: parts[4].parse().unwrap_or(0),
                memory_total_mb: parts[5].parse().unwrap_or(0),
                power_draw_w: parts[6].parse().unwrap_or(0.0),
            });
        }
    }
    gpus
}

/// Remote node definition for fleet discovery
pub struct RemoteNode {
    pub name: String,
    pub ip: String,
    pub ssh_user: String,
}

fn known_remote_nodes() -> Vec<RemoteNode> {
    vec![
        RemoteNode { name: "cesarops4".into(), ip: "10.0.0.41".into(), ssh_user: "cesarops".into() },
        RemoteNode { name: "cesarops2".into(), ip: "10.0.0.201".into(), ssh_user: "cesarops".into() },
        RemoteNode { name: "cesarops3".into(), ip: "10.0.0.111".into(), ssh_user: "cesarops".into() },
    ]
}

/// Full fleet GPU summary: local + remote nodes via SSH fallback
pub async fn full_fleet_gpu_summary() -> serde_json::Value {
    // Local GPUs
    let local = query_gpu_metrics().await;

    // Remote nodes in parallel
    let remote_nodes = known_remote_nodes();
    let remote_futures: Vec<_> = remote_nodes.iter().map(|node| {
        let ip = node.ip.clone();
        let user = node.ssh_user.clone();
        let name = node.name.clone();
        async move {
            let gpus = query_remote_gpu_metrics(&ip, &user).await;
            (name, ip, gpus)
        }
    }).collect();

    let remote_results = futures::future::join_all(remote_futures).await;

    // Build combined node list
    let mut all_nodes = vec![
        serde_json::json!({
            "name": "t440",
            "ip": "10.0.0.61",
            "local": true,
            "gpus": local.gpus,
            "error": local.error,
        })
    ];

    for (name, ip, gpus) in remote_results {
        let error = if gpus.is_empty() { Some(format!("No GPU data from {}", ip)) } else { None };
        all_nodes.push(serde_json::json!({
            "name": name,
            "ip": ip,
            "local": false,
            "gpus": gpus,
            "error": error,
        }));
    }

    serde_json::json!({ "nodes": all_nodes })
}

/// Get a summary of cluster health for the /monitor endpoint.
pub async fn cluster_summary() -> serde_json::Value {
    let gpu = query_gpu_metrics().await;

    // Also query remote nodes via SSH for their GPUs
    let remote_nodes = known_remote_nodes();
    let remote_futures: Vec<_> = remote_nodes.iter().map(|node| {
        let ip = node.ip.clone();
        let user = node.ssh_user.clone();
        let name = node.name.clone();
        async move {
            let gpus = query_remote_gpu_metrics(&ip, &user).await;
            (name, ip, gpus)
        }
    }).collect();
    let remote_results = futures::future::join_all(remote_futures).await;

    // Build enriched remote nodes JSON for the UI
    let remote_nodes_json: Vec<serde_json::Value> = remote_results.into_iter().map(|(name, ip, gpus)| {
        let reachable = !gpus.is_empty();
        serde_json::json!({
            "name": name,
            "ip": ip,
            "gpus": gpus,
            "gpu_count": gpus.len(),
            "reachable": reachable,
        })
    }).collect();
    
    // Parse workers to pass down GPU mappings for the dashboard
    let mut workers_info = Vec::new();
    if let Ok(content) = std::fs::read_to_string(crate::paths::cluster_config_path()) {
        if let Ok(table) = content.parse::<toml::Table>() {
            if let Some(workers) = table.get("worker").and_then(|v| v.as_array()) {
                for w in workers {
                    if let Some(t) = w.as_table() {
                        let mut w_json = serde_json::Map::new();
                        if let Some(name) = t.get("name").and_then(|v| v.as_str()) {
                            w_json.insert("name".to_string(), serde_json::json!(name));
                        }
                        if let Some(role) = t.get("role").and_then(|v| v.as_str()) {
                            w_json.insert("role".to_string(), serde_json::json!(role));
                        }
                        if let Some(gpu_val) = t.get("gpu").and_then(|v| v.as_integer()) {
                            w_json.insert("gpu".to_string(), serde_json::json!(gpu_val));
                        }
                        if let Some(gpu_ids) = t.get("gpu_ids").and_then(|v| v.as_str()) {
                            w_json.insert("gpu_ids".to_string(), serde_json::json!(gpu_ids));
                        }
                        workers_info.push(serde_json::Value::Object(w_json));
                    }
                }
            }
        }
    }

    let caps = crate::orchestrator::probe_cluster_capabilities().await;
    
    serde_json::json!({
        "gpus": gpu.gpus,
        "gpu_error": gpu.error,
        "workers": workers_info,
        "nodes": caps,
        "remote_nodes": remote_nodes_json,
        "avx512_note": "Limit AVX-512 to 8 cores (Socket 0) to avoid throttle",
        "numa": {
            "socket_0": "Cores 0-7, P100 #0, DDR4 Ch 0-2",
            "socket_1": "Cores 8-15, P100 #1, DDR4 Ch 3-5",
        },
    })
}
