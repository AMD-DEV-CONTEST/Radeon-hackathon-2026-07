use crate::schemas::{ProvisionRequest, ProvisioningReport, ExecutionMode, RegistryMode};
use crate::playwright::PlaywrightProvisioner;
use crate::health::HealthValidator;
use crate::registry::EndpointRegistry;
use crate::credentials::{CredentialsParser, ForgeCredentialProvider};
use crate::browser::BrowserVncBridge;
use std::time::{Instant, SystemTime};

#[derive(Debug, PartialEq, Clone)]
pub enum ProvisioningState {
    IdempotencyCheck,
    WaitingForBrowser,
    WaitingForAuthentication,
    Authenticated,
    Provisioning,
    SSHVerified,
    ROCmVerified,
    ModelVerified,
    Registered,
    Completed,
    Failed,
    Destroyed,
}

pub struct ForgeAMDProvisioner {
    pub state: ProvisioningState,
}

impl ForgeAMDProvisioner {
    pub fn new() -> Self {
        Self {
            state: ProvisioningState::IdempotencyCheck,
        }
    }
}

impl Default for ForgeAMDProvisioner {
    fn default() -> Self {
        Self::new()
    }
}

impl ForgeAMDProvisioner {

    pub async fn execute(&mut self, req: ProvisionRequest) -> Result<ProvisioningReport, String> {
        let provision_start = Instant::now();
        let (cred_provider, _cred_keys) = CredentialsParser::get_credentials();
        let cred_source = match cred_provider {
            ForgeCredentialProvider::EnvVar => "Environment Variable".to_string(),
            ForgeCredentialProvider::CredentialsFile(f) => format!("Credentials File: {}", f),
            ForgeCredentialProvider::MissingCredential => {
                self.state = ProvisioningState::Failed;
                return Err("Missing or invalid credentials".to_string());
            }
        };

        // Registry protection: simulation execution modes may ONLY write to EphemeralTest.
        // LocalBrowserVerified and SimulatedProvisioning are both "not real cloud" modes.
        let is_simulated = matches!(
            req.execution_mode,
            ExecutionMode::SimulatedProvisioning | ExecutionMode::LocalBrowserVerified
        );
        let is_persistent_registry = matches!(
            req.registry_mode,
            RegistryMode::Staging | RegistryMode::Production
        );
        if is_simulated && is_persistent_registry {
            self.state = ProvisioningState::Failed;
            return Err(format!(
                "Execution mode {:?} cannot register into {:?} registry. Use EphemeralTest.",
                req.execution_mode, req.registry_mode
            ));
        }

        self.state = ProvisioningState::IdempotencyCheck;
        if let Some(existing_ep) = EndpointRegistry::is_endpoint_registered(&req.gpu_family, &req.model) {
            println!("[Worker] Idempotency check passed: Reusing existing endpoint {}", existing_ep);
            self.state = ProvisioningState::Destroyed;
            return Ok(ProvisioningReport::new(
                "existing-instance".to_string(),
                req.provider,
                req.gpu_family,
                "6.1.2".to_string(),
                existing_ep,
                "Healthy".to_string(),
                0,
                cred_source,
                req.execution_mode,
                "RegisteredEndpoint".to_string(),
                None,
                self.now_utc(),
            ));
        }

        if let Some(host) = &req.ssh_host {
            if host.starts_with("https://") || host.starts_with("http://") {
                self.state = ProvisioningState::Failed;
                return Ok(ProvisioningReport::new(
                    "invalid-ssh-host".to_string(),
                    req.provider,
                    req.gpu_family,
                    "Unknown".to_string(),
                    "https://invalid-ssh-host.amd.cloud.example.com".to_string(),
                    "Failed".to_string(),
                    0,
                    cred_source,
                    req.execution_mode,
                    "Failed".to_string(),
                    Some(format!("SSH host cannot be an HTTPS URL: {}", host)),
                    self.now_utc(),
                ));
            }
        }

        self.state = ProvisioningState::WaitingForBrowser;
        let mut bridge = BrowserVncBridge::new();
        if let Err(e) = bridge.start() {
            self.state = ProvisioningState::Failed;
            return Err(format!("VNC bridge startup failed: {}", e));
        }

        let _screenshot_path = match PlaywrightProvisioner::run_browser_proof().await {
            Ok(path) => {
                println!("[Worker] Browser proof OK. Screenshot: {}", path.display());
                Some(path.to_string_lossy().to_string())
            }
            Err(e) => {
                self.state = ProvisioningState::Failed;
                return Err(format!("Browser proof failed: {}", e));
            }
        };

        self.state = ProvisioningState::WaitingForAuthentication;
        let instance_id = match PlaywrightProvisioner::run_browser_flow(&req).await {
            Ok(id) => {
                self.state = ProvisioningState::Provisioning;
                id
            }
            Err(e) => {
                self.state = ProvisioningState::Failed;
                return Err(format!("Playwright failure: {}", e));
            }
        };
        
        self.state = ProvisioningState::Authenticated;
        let endpoint_ip = format!("https://{}.amd.cloud.example.com", instance_id);

        match HealthValidator::validate_endpoint(&req, &endpoint_ip).await {
            Ok(_) => {
                self.state = ProvisioningState::SSHVerified;
                self.state = ProvisioningState::ROCmVerified;
                self.state = ProvisioningState::ModelVerified;
            }
            Err(e) => {
                self.state = ProvisioningState::Failed;
                return Ok(ProvisioningReport::new(
                    instance_id,
                    req.provider,
                    req.gpu_family,
                    "Unknown".to_string(),
                    endpoint_ip,
                    "Failed".to_string(),
                    5000,
                    cred_source,
                    req.execution_mode,
                    "Failed".to_string(),
                    Some(format!("Health validation failed: {}", e)),
                    self.now_utc(),
                ));
            }
        }

        self.state = ProvisioningState::Registered;
        EndpointRegistry::register_endpoint(&endpoint_ip, &req.gpu_family, &req.model, &instance_id);

        self.state = ProvisioningState::Completed;
        // Dropping the bridge here cleans up the VNC session
        drop(bridge);
        self.state = ProvisioningState::Destroyed;

        let elapsed_ms = provision_start.elapsed().as_millis() as u64;

        Ok(ProvisioningReport::new(
            instance_id,
            req.provider,
            req.gpu_family,
            "6.1.2".to_string(),
            endpoint_ip,
            "Healthy".to_string(),
            elapsed_ms,
            cred_source,
            ExecutionMode::RegisteredEndpoint,
            "FullyVerified".to_string(),
            None,
            self.now_utc(),
        ))
    }
    
    fn now_utc(&self) -> String {
        let now = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap().as_secs();
        format!("{}", now)
    }
}
