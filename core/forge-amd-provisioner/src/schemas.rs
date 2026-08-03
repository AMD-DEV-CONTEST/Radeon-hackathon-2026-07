use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use hex;

pub fn deterministic_hash<T: Serialize>(obj: &T) -> String {
    let serialized = serde_json::to_string(obj).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    hex::encode(hasher.finalize())
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ExecutionMode {
    SimulatedProvisioning,
    LocalBrowserVerified,
    AuthenticatedSession,
    CloudProvisioned,
    SSHVerified,
    ROCmVerified,
    ModelEndpointVerified,
    RegisteredEndpoint,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum RegistryMode {
    EphemeralTest,
    Staging,
    Production,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProvisionRequest {
    pub provider: String,
    pub instance_type: String,
    pub gpu_family: String,
    pub image: String,
    pub model: String,
    pub startup_script: String,
    pub timeout: u64,
    pub health_endpoint: String,
    pub required_memory: u64,
    pub required_vram: u64,
    pub execution_mode: ExecutionMode,
    pub registry_mode: RegistryMode,
    pub ssh_host: Option<String>,
    pub ssh_port: Option<u16>,
    pub ssh_user: Option<String>,
}

impl ProvisionRequest {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProvisioningReport {
    pub instance_id: String,
    pub provider: String,
    pub gpu: String,
    pub rocm_version: String,
    pub endpoint: String,
    pub health_status: String,
    pub startup_duration: u64,
    pub credential_source: String,
    pub execution_mode: ExecutionMode,
    pub validation_state: String,
    pub failure_reason: Option<String>,
    pub timestamp: String,
    pub deterministic_hash: String,
}

impl ProvisioningReport {
    pub fn new(
        instance_id: String,
        provider: String,
        gpu: String,
        rocm_version: String,
        endpoint: String,
        health_status: String,
        startup_duration: u64,
        credential_source: String,
        execution_mode: ExecutionMode,
        validation_state: String,
        failure_reason: Option<String>,
        timestamp: String,
    ) -> Self {
        let mut report = Self {
            instance_id,
            provider,
            gpu,
            rocm_version,
            endpoint,
            health_status,
            startup_duration,
            credential_source,
            execution_mode,
            validation_state,
            failure_reason,
            timestamp,
            deterministic_hash: String::new(),
        };
        report.deterministic_hash = deterministic_hash(&report);
        report
    }
}
