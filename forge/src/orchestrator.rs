use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use tokio::process::Command;
use tracing::{info, warn};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeCapabilities {
    pub name: String,
    pub ip: String,
    pub free_vram_mb: u32,
    pub system_ram_mb: u32,
    pub cpu_usage: f32,
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct HardwareStats {
    pub free_vram_mb: u32,
    pub system_ram_mb: u32,
    pub cpu_usage: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelRecommendation {
    pub model_name: String,
    pub model_path: String,
    pub size_gb: f64,
    pub recommended_node: Option<String>,
}

fn get_known_nodes() -> Vec<(String, String)> {
    vec![
        ("cesarops2".to_string(), "10.0.0.201".to_string()),
        ("cesarops3".to_string(), "10.0.0.111".to_string()),
        ("cesarops4".to_string(), "10.0.0.41".to_string()),
        ("mi300".to_string(), "134.199.203.198".to_string()),
        ("t440".to_string(), "10.0.0.61".to_string()),
    ]
}

/// Probes cluster via HTTP sidecar on port 9101
pub async fn probe_cluster_capabilities() -> Vec<NodeCapabilities> {
    let mut results = Vec::new();
    let nodes = get_known_nodes();
    let client = reqwest::Client::builder().timeout(std::time::Duration::from_secs(3)).build().unwrap();

    for (name, ip) in nodes {
        let url = format!("http://{}:9101/stats", ip);
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                if let Ok(stats) = resp.json::<HardwareStats>().await {
                    results.push(NodeCapabilities {
                        name,
                        ip,
                        free_vram_mb: stats.free_vram_mb,
                        system_ram_mb: stats.system_ram_mb,
                        cpu_usage: stats.cpu_usage,
                        error: None,
                    });
                } else {
                    results.push(NodeCapabilities {
                        name,
                        ip,
                        free_vram_mb: 0,
                        system_ram_mb: 0,
                        cpu_usage: 0.0,
                        error: Some("Failed to parse JSON".into()),
                    });
                }
            }
            Ok(resp) => {
                results.push(NodeCapabilities {
                    name,
                    ip,
                    free_vram_mb: 0,
                    system_ram_mb: 0,
                    cpu_usage: 0.0,
                    error: Some(format!("HTTP error: {}", resp.status())),
                });
            }
            Err(e) => {
                results.push(NodeCapabilities {
                    name,
                    ip,
                    free_vram_mb: 0,
                    system_ram_mb: 0,
                    cpu_usage: 0.0,
                    error: Some(e.to_string()),
                });
            }
        }
    }
    results
}

fn get_dir_size(path: &Path) -> u64 {
    let mut size = 0;
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            if let Ok(meta) = entry.metadata() {
                if meta.is_dir() {
                    size += get_dir_size(&entry.path());
                } else {
                    size += meta.len();
                }
            }
        }
    }
    size
}

pub async fn get_model_recommendations() -> Vec<ModelRecommendation> {
    let mut recommendations = Vec::new();
    let models_dir = "/mnt/raid0/models";
    
    // Probe cluster capabilities
    let caps = probe_cluster_capabilities().await;
    // Map node name to free MB
    let mut vram_map: HashMap<String, u32> = HashMap::new();
    for status in caps {
        vram_map.insert(status.name, status.free_vram_mb);
    }

    if let Ok(entries) = std::fs::read_dir(models_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            let is_gguf = path.extension().and_then(|e| e.to_str()) == Some("gguf");
            let is_dir = path.is_dir();
            
            if is_gguf || is_dir {
                let size_bytes = if is_dir { get_dir_size(&path) } else { entry.metadata().map(|m| m.len()).unwrap_or(0) };
                
                if size_bytes > 0 {
                    let size_gb = size_bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                    let required_vram_mb = (size_gb * 1.2 * 1024.0) as u32; // Rough overhead estimate

                    let mut recommended = None;
                    
                    // Greedy fit: find first node with enough VRAM
                    for (node, free_mb) in &vram_map {
                        if *free_mb > required_vram_mb {
                            recommended = Some(node.clone());
                            break;
                        }
                    }
                    
                    // Fallback to static rules if dynamic probe failed / not enough
                    if recommended.is_none() {
                        if size_gb < 8.0 {
                            recommended = Some("cesarops3".to_string());
                        } else if size_gb < 15.0 {
                            recommended = Some("cesarops4".to_string());
                        } else if size_gb < 20.0 {
                            recommended = Some("t440".to_string());
                        } else {
                            recommended = Some("cesarops2".to_string());
                        }
                    }

                    recommendations.push(ModelRecommendation {
                        model_name: path.file_name().unwrap_or_default().to_string_lossy().to_string(),
                        model_path: path.to_string_lossy().to_string(),
                        size_gb,
                        recommended_node: recommended,
                    });
                }
            }
        }
    }
    recommendations
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeploymentContract {
    pub model_name: String,
    pub target_node: String,
    #[serde(default)]
    pub engine: String, // e.g. "llama.cpp", "vllm", "koboldcpp"
    #[serde(default)]
    pub backend: String, // e.g. "cuda", "vulkan", "cpu"
    #[serde(default)]
    pub tensor_split: Option<String>,
    #[serde(default)]
    pub gpu_ids: Option<String>,
    #[serde(default)]
    pub context_size: Option<u32>,
}

pub async fn hotswap_model(req: DeploymentContract) -> Result<String, String> {
    // Basic lookup for IP
    let ip = match req.target_node.as_str() {
        "cesarops2" => "10.0.0.201",
        "cesarops3" => "10.0.0.111",
        "cesarops4" => "10.0.0.41",
        "t440" => "10.0.0.61",
        "mi300" => "134.199.203.198",
        _ => return Err("Unknown node".into()),
    };

    let url = format!("http://{}:9101/deploy", ip);
    let client = reqwest::Client::new();
    
    match client.post(&url).json(&req).send().await {
        Ok(resp) if resp.status().is_success() => Ok(format!("Successfully dispatched {} to {} via Sidecar", req.model_name, req.target_node)),
        Ok(resp) => Err(format!("Sidecar returned error: {}", resp.status())),
        Err(e) => Err(format!("Failed to reach sidecar on {}: {}", ip, e)),
    }
}

pub async fn teardown_model(target_node: String) -> Result<String, String> {
    let ip = match target_node.as_str() {
        "cesarops2" => "10.0.0.201",
        "cesarops3" => "10.0.0.111",
        "cesarops4" => "10.0.0.41",
        "t440" => "10.0.0.61",
        "mi300" => "134.199.203.198",
        _ => return Err("Unknown node".into()),
    };

    let url = format!("http://{}:9101/teardown", ip);
    let client = reqwest::Client::new();
    
    match client.post(&url).send().await {
        Ok(resp) if resp.status().is_success() => Ok(format!("Successfully tore down models on {}", target_node)),
        Ok(resp) => Err(format!("Sidecar returned error: {}", resp.status())),
        Err(e) => Err(format!("Failed to reach sidecar on {}: {}", ip, e)),
    }
}
