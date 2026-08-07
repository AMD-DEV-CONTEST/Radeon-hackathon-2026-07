use axum::{routing::{get, post}, Json, Router};
use serde::{Deserialize, Serialize};
use sysinfo::System;
use std::process::Command;

#[derive(Serialize, Deserialize, Debug)]
pub struct HardwareStats {
    pub free_vram_mb: u32,
    pub system_ram_mb: u32,
    pub cpu_usage: f32,
    pub accelerators: Vec<AcceleratorStatus>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct AcceleratorStatus {
    pub vendor: String,
    pub name: String,
    pub status: String,
}

// Wrapper for Movidius
fn get_movidius_status() -> Option<AcceleratorStatus> {
    // Placeholder for Movidius sysfs logic
    None
}

// Wrapper for TPU
fn get_tpu_status() -> Option<AcceleratorStatus> {
    // Placeholder for TPU logic (e.g. gflot or sysfs)
    None
}

// Wrapper for all-smi
fn get_all_smi_vram() -> u32 {
    // Since all-smi is mainly a CLI utility for generalized monitoring,
    // we can either parse its CLI output or use its lib API if exposed.
    // For now, we will shell out to `all-smi` if it's installed as a binary,
    // or return a stub.
    
    // Stub until we parse exact all-smi output formats
    // let output = Command::new("all-smi").output().ok()?;
    0
}

async fn get_stats() -> Json<HardwareStats> {
    let mut sys = System::new_all();
    sys.refresh_all();
    
    let system_ram_mb = (sys.available_memory() / 1024 / 1024) as u32;
    let cpu_usage = sys.global_cpu_info().cpu_usage();
    
    let free_vram_mb = get_all_smi_vram();
    
    let mut accelerators = Vec::new();
    if let Some(mov) = get_movidius_status() {
        accelerators.push(mov);
    }
    if let Some(tpu) = get_tpu_status() {
        accelerators.push(tpu);
    }
    
    Json(HardwareStats {
        free_vram_mb,
        system_ram_mb,
        cpu_usage,
        accelerators,
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeploymentContract {
    pub model_name: String,
    pub target_node: String,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub backend: String,
    #[serde(default)]
    pub tensor_split: Option<String>,
    #[serde(default)]
    pub gpu_ids: Option<String>,
    #[serde(default)]
    pub context_size: Option<u32>,
}

async fn deploy_model(Json(req): Json<DeploymentContract>) -> Json<serde_json::Value> {
    println!("Received deploy request: {:?}", req);
    
    // 1. Kill existing servers locally first
    let _ = Command::new("bash")
        .arg("-c")
        .arg("pkill -f llama-server; pkill -f paddler; pkill -f vllm")
        .status();

    // 2. Prepare environment variables
    let mut env_prefix = String::new();
    if let Some(gpus) = &req.gpu_ids {
        env_prefix.push_str(&format!("CUDA_VISIBLE_DEVICES={} ", gpus));
    }
    
    let mut is_droplet = false;
    if let Ok(hostname) = std::fs::read_to_string("/etc/hostname") {
        if hostname.trim() == "0" {
            is_droplet = true;
        }
    }

    let mut model_path = if is_droplet {
        format!("/shared-docker/models/{}", req.model_name)
    } else {
        format!("/mnt/raid0/models/{}", req.model_name)
    };
    
    // Auto-resolve GGUF file if path is a directory
    if let Ok(entries) = std::fs::read_dir(&model_path) {
        for entry in entries.flatten() {
            if let Some(ext) = entry.path().extension() {
                if ext == "gguf" {
                    model_path = entry.path().to_string_lossy().to_string();
                    break;
                }
            }
        }
    }
    
    let port = 8080;
    let engine = if req.engine.is_empty() { "llama.cpp" } else { req.engine.as_str() };
    
    let engine_cmd = match engine {
        "llama.cpp" | "llama-server" => {
            let mut cmd = format!("/home/cesarops/bin/llama-server -m {} -ngl 99 --port {} --host 0.0.0.0", model_path, port);
            if let Some(ctx) = req.context_size {
                cmd.push_str(&format!(" -c {}", ctx));
            }
            if let Some(ts) = &req.tensor_split {
                cmd.push_str(&format!(" --tensor-split {}", ts));
            }
            cmd
        },
        "vllm" => {
            let mut cmd = if is_droplet {
                format!("vllm serve {} --port {} --host 0.0.0.0", model_path, port)
            } else {
                format!("python3 -m vllm.entrypoints.openai.api_server --model {} --port {} --host 0.0.0.0", model_path, port)
            };
            if let Some(ts) = &req.tensor_split {
                let count = ts.split(',').count();
                cmd.push_str(&format!(" --tensor-parallel-size {}", count));
            }
            cmd
        },
        _ => {
            return Json(serde_json::json!({"status": "error", "message": format!("Unsupported engine: {}", engine)}));
        }
    };
    
    // Start engine locally in background
    let launch_cmd = format!("nohup bash -c '{} {} > /tmp/engine.log 2>&1' &", env_prefix, engine_cmd);
    let _ = Command::new("bash").arg("-c").arg(&launch_cmd).spawn();
    
    // Start paddler agent
    // Assuming the sidecar is always run on a node managed by the central cluster at 10.0.0.61:8060
    let paddler_cmd = format!("nohup /home/cesarops/bin/paddler agent --management-addr 10.0.0.61:8060 --slots 1 --name {} > /tmp/paddler_agent.log 2>&1 &", req.target_node);
    let _ = Command::new("bash").arg("-c").arg(&paddler_cmd).spawn();

    Json(serde_json::json!({
        "status": "success",
        "message": format!("Successfully dispatched {} via {} to local node", req.model_name, engine)
    }))
}

async fn teardown_models() -> Json<serde_json::Value> {
    println!("Received teardown request");
    let _ = Command::new("bash")
        .arg("-c")
        .arg("pkill -f llama-server; pkill -f paddler; pkill -f vllm")
        .status();

    Json(serde_json::json!({
        "status": "success",
        "message": "Local inference servers torn down"
    }))
}

#[tokio::main]
async fn main() {
    let app = Router::new()
        .route("/stats", get(get_stats))
        .route("/deploy", post(deploy_model))
        .route("/teardown", post(teardown_models));
    
    // Start sidecar on 9101
    let addr = "0.0.0.0:9101";
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    println!("Hardware sidecar listening on {}", addr);
    axum::serve(listener, app).await.unwrap();
}
