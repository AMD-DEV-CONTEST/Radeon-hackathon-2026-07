//! Hardware Archaeologist — audits the system at startup.
//! Detects GPUs, CPUs, NUMA topology, and determines model sharding strategy.
//!
//! NOTE: wgpu enumeration requires the wgpu crate. For now, we use nvidia-smi
//! parsing (same approach as forge-v2/hardware.rs) to avoid the heavy dep.

use std::fs;
use tracing::info;

/// Complete hardware profile of the system.
#[derive(Debug, Clone)]
pub struct IronProfile {
    pub gpu_nodes: Vec<GpuNodeInfo>,
    pub cpu_nodes: Vec<CpuNode>,
    pub total_vram_mb: u64,
    pub total_host_ram_mb: u64,
    pub numa_node_count: u32,
}

/// GPU info for inference planning.
#[derive(Debug, Clone)]
pub struct GpuNodeInfo {
    pub index: usize,
    pub name: String,
    pub vram_mb: u64,
    pub supports_f16: bool,
}

/// CPU socket info.
#[derive(Debug, Clone)]
pub struct CpuNode {
    pub socket_id: u32,
    pub core_count: u32,
    pub has_avx512: bool,
}

/// Audit the system hardware via nvidia-smi and /proc.
pub fn audit_system() -> IronProfile {
    let gpu_nodes = detect_gpus();
    let cpu_nodes = detect_cpus();
    let total_host_ram_mb = read_total_ram_mb();
    let total_vram_mb: u64 = gpu_nodes.iter().map(|g| g.vram_mb).sum();
    let numa_node_count = detect_numa_nodes();

    let profile = IronProfile {
        gpu_nodes,
        cpu_nodes,
        total_vram_mb,
        total_host_ram_mb,
        numa_node_count,
    };

    info!("IronProfile: {} GPUs ({} MB VRAM), {} MB host RAM, {} NUMA nodes",
        profile.gpu_nodes.len(), profile.total_vram_mb,
        profile.total_host_ram_mb, profile.numa_node_count);

    profile
}

/// Detect GPUs via nvidia-smi CSV parsing.
fn detect_gpus() -> Vec<GpuNodeInfo> {
    let output = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"])
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            stdout.lines().enumerate().filter_map(|(i, line)| {
                let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
                if parts.len() >= 3 {
                    let name = parts[1].to_string();
                    let vram_mb = parts[2].parse::<u64>().unwrap_or(0);
                    let supports_f16 = name.contains("P100") || name.contains("V100");
                    Some(GpuNodeInfo { index: i, name, vram_mb, supports_f16 })
                } else {
                    None
                }
            }).collect()
        }
        _ => Vec::new(),
    }
}

/// Detect CPU sockets and AVX-512 support.
fn detect_cpus() -> Vec<CpuNode> {
    #[cfg(target_arch = "x86_64")]
    let has_avx512 = is_x86_feature_detected!("avx512f");
    #[cfg(not(target_arch = "x86_64"))]
    let has_avx512 = false;

    let socket_count = fs::read_to_string("/sys/devices/system/node/online")
        .ok()
        .and_then(|s| {
            let parts: Vec<&str> = s.trim().split('-').collect();
            parts.last().and_then(|n| n.parse::<u32>().ok()).map(|n| n + 1)
        })
        .unwrap_or(1);

    let total_cores: u32 = fs::read_to_string("/proc/cpuinfo")
        .ok()
        .map(|s| s.matches("processor").count() as u32)
        .unwrap_or(1);

    let cores_per_socket = total_cores / socket_count;

    (0..socket_count).map(|socket_id| CpuNode {
        socket_id,
        core_count: cores_per_socket,
        has_avx512,
    }).collect()
}

fn read_total_ram_mb() -> u64 {
    fs::read_to_string("/proc/meminfo")
        .ok()
        .and_then(|content| {
            content.lines()
                .find(|line| line.starts_with("MemTotal:"))
                .and_then(|line| line.split_whitespace().nth(1)?.parse::<u64>().ok())
        })
        .map(|kb| kb / 1024)
        .unwrap_or(0)
}

fn detect_numa_nodes() -> u32 {
    fs::read_to_string("/sys/devices/system/node/online")
        .ok()
        .and_then(|s| {
            let parts: Vec<&str> = s.trim().split('-').collect();
            parts.last().and_then(|n| n.parse::<u32>().ok()).map(|n| n + 1)
        })
        .unwrap_or(1)
}
