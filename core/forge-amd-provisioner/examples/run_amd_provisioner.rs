use forge_amd_provisioner::schemas::{ProvisionRequest, ExecutionMode, RegistryMode};
use forge_amd_provisioner::worker::ForgeAMDProvisioner;
use std::env;

#[tokio::main]
async fn main() {
    println!("============================================================");
    println!("FORGE AMD PROVISIONER DEMONSTRATION (MissionSpec Integrated)");
    println!("============================================================\n");
    
    // Setup valid env vars for demo
    env::set_var("AMD_CLOUD_USER", "admin");
    env::set_var("AMD_CLOUD_PASS", "demo");

    let req = ProvisionRequest {
        provider: "AMDDeveloperCloud".to_string(),
        instance_type: "MI300X-8G".to_string(),
        gpu_family: "MI300X".to_string(),
        image: "rocm-6.1.2-ubuntu22.04".to_string(),
        model: "Llama-3-70B-Instruct".to_string(),
        startup_script: "vllm serve --tensor-parallel-size 8".to_string(),
        timeout: 3600,
        health_endpoint: "/v1/models".to_string(),
        required_memory: 512,
        required_vram: 1536,
        execution_mode: ExecutionMode::AuthenticatedSession,
        registry_mode: RegistryMode::Staging,
        ssh_host: Some("1.2.3.4".to_string()),
        ssh_port: Some(22),
        ssh_user: Some("ubuntu".to_string()),
    };

    println!("1. Submitting ProvisionRequest to ForgeAMDProvisioner...");
    println!("   Model: {}", req.model);
    println!("   GPU Required: {}", req.gpu_family);

    let mut provisioner = ForgeAMDProvisioner::new();
    
    match provisioner.execute(req).await {
        Ok(report) => {
            println!("\n============================================================");
            println!("PROVISIONING COMPLETED");
            println!("============================================================");
            println!("Report Hash: {}", report.deterministic_hash);
            println!("Instance ID: {}", report.instance_id);
            println!("Assigned Endpoint: {}", report.endpoint);
            println!("Health Status: {}", report.health_status);
            println!("Credential Source: {}", report.credential_source);
            println!("Execution Mode: {:?}", report.execution_mode);
            println!("\nForge Endpoint Registry is now ready for Paddler routing.");
        }
        Err(e) => {
            println!("\n[FATAL] Provisioning Failed: {}", e);
        }
    }
}
