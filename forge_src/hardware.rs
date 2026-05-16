use serde::Serialize;
use tokio::process::Command;

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

/// Get a summary of cluster health for the /monitor endpoint.
pub async fn cluster_summary() -> serde_json::Value {
    let gpu = query_gpu_metrics().await;

    serde_json::json!({
        "gpus": gpu.gpus,
        "gpu_error": gpu.error,
        "avx512_note": "Limit AVX-512 to 8 cores (Socket 0) to avoid throttle",
        "numa": {
            "socket_0": "Cores 0-7, P100 #0, DDR4 Ch 0-2",
            "socket_1": "Cores 8-15, P100 #1, DDR4 Ch 3-5",
        },
    })
}
