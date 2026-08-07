use std::env;
use std::fs;
use std::path::Path;

/// Manages integration with the existing Forge/Paddler endpoint registry.
/// Implements idempotent endpoint creation.
///
/// The registry path defaults to `endpoints.json` in the process CWD,
/// but can be overridden with the `FORGE_REGISTRY_PATH` environment variable.
/// Tests must set this to an isolated path to avoid cross-test contamination.
pub struct EndpointRegistry;

impl EndpointRegistry {
    fn registry_path() -> String {
        env::var("FORGE_REGISTRY_PATH").unwrap_or_else(|_| "endpoints.json".to_string())
    }

    pub fn is_endpoint_registered(gpu_family: &str, model: &str) -> Option<String> {
        let registry_path = Self::registry_path();
        if !Path::new(&registry_path).exists() {
            return None;
        }

        let content = fs::read_to_string(&registry_path).unwrap_or_default();
        let endpoints: Vec<serde_json::Value> =
            serde_json::from_str(&content).unwrap_or_default();

        for ep in endpoints {
            if ep["gpu_family"] == gpu_family
                && ep["model"] == model
                && ep["status"] == "active"
            {
                return ep["endpoint"].as_str().map(|s| s.to_string());
            }
        }
        None
    }

    pub fn register_endpoint(
        endpoint: &str,
        gpu_family: &str,
        model: &str,
        instance_id: &str,
    ) {
        let registry_path = Self::registry_path();
        let mut endpoints: Vec<serde_json::Value> = if Path::new(&registry_path).exists() {
            let content = fs::read_to_string(&registry_path).unwrap_or_default();
            serde_json::from_str(&content).unwrap_or_default()
        } else {
            vec![]
        };

        let new_entry = serde_json::json!({
            "endpoint": endpoint,
            "gpu_family": gpu_family,
            "model": model,
            "instance_id": instance_id,
            "status": "active"
        });

        endpoints.push(new_entry);
        fs::write(
            &registry_path,
            serde_json::to_string_pretty(&endpoints).unwrap(),
        )
        .unwrap();
        println!(
            "[Registry] Successfully registered new Forge endpoint: {}",
            endpoint
        );
    }
}
