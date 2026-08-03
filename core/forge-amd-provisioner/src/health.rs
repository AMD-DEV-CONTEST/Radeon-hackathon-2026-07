use crate::schemas::ProvisionRequest;
use std::net::TcpStream;
use std::time::Duration;

pub struct HealthValidator;

impl HealthValidator {
    /// Validates a provisioned endpoint through three real checks:
    ///
    /// 1. TCP reachability of the SSH host (no credentials required).
    /// 2. rocm-smi validation is deferred until an actual cloud instance is
    ///    available (requires SSH credentials and a running instance).
    /// 3. HTTP GET to the inference health endpoint.
    ///
    /// Returns Ok("Healthy") only when all checks that can be performed
    /// locally succeed.  Returns Err with a specific message on first failure.
    pub async fn validate_endpoint(
        req: &ProvisionRequest,
        endpoint_url: &str,
    ) -> Result<String, String> {
        // ── Guard: SSH host must not be an HTTPS URL ──────────────────────
        if let Some(host) = &req.ssh_host {
            if host.starts_with("https://") || host.starts_with("http://") {
                return Err("SSH host cannot be an HTTPS URL".to_string());
            }

            // ── Check 1: TCP reachability of the SSH host ─────────────────
            let port = req.ssh_port.unwrap_or(22);
            let addr = format!("{}:{}", host, port);
            println!("[Validation] Probing TCP {}...", addr);

            match TcpStream::connect_timeout(
                &addr.parse().map_err(|e| format!("Bad SSH address '{}': {}", addr, e))?,
                Duration::from_secs(5),
            ) {
                Ok(_) => {
                    println!("[Validation] TCP connection to {} succeeded.", addr);
                }
                Err(e) => {
                    return Err(format!(
                        "SSH TCP probe failed for '{}': {}",
                        addr, e
                    ));
                }
            }

            // ── Check 2: ROCm (Real SSH check) ───────────
            let user = req.ssh_user.as_deref().unwrap_or("amd");
            println!("[Validation] Executing rocm-smi via SSH ({}@{})...", user, host);

            let ssh_output = std::process::Command::new("ssh")
                .arg("-o")
                .arg("StrictHostKeyChecking=no")
                .arg("-o")
                .arg("UserKnownHostsFile=/dev/null")
                .arg("-o")
                .arg("BatchMode=yes") // Fail instead of prompting for password
                .arg("-o")
                .arg("ConnectTimeout=10")
                .arg("-p")
                .arg(port.to_string())
                .arg(format!("{}@{}", user, host))
                .arg("rocm-smi")
                .arg("--json")
                .output()
                .map_err(|e| format!("Failed to spawn ssh command: {}", e))?;

            if !ssh_output.status.success() {
                let stderr = String::from_utf8_lossy(&ssh_output.stderr);
                // For demonstration, if SSH fails (e.g. because we are probing a fake IP or
                // don't have keys loaded locally), we still propagate the error honestly.
                return Err(format!("ROCm SSH check failed: {}", stderr.trim()));
            }

            let stdout = String::from_utf8_lossy(&ssh_output.stdout);
            if !stdout.contains("card") && !stdout.contains("GPU") {
                return Err(format!("ROCm JSON output invalid or no GPUs found."));
            }

            println!("[Validation] ROCm SSH check succeeded.");
        }

        // ── Check 3: HTTP health endpoint ─────────────────────────────────
        let health_url = format!("{}{}", endpoint_url.trim_end_matches('/'), req.health_endpoint);
        println!("[Validation] HTTP GET {}...", health_url);

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|e| format!("HTTP client build failed: {}", e))?;

        match client.get(&health_url).send().await {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    println!(
                        "[Validation] Health endpoint responded: HTTP {}",
                        status
                    );
                } else {
                    return Err(format!(
                        "Health endpoint {} returned HTTP {}",
                        health_url, status
                    ));
                }
            }
            Err(e) => {
                // Connection refused / DNS failure = endpoint not ready.
                return Err(format!(
                    "Health endpoint unreachable '{}': {}",
                    health_url, e
                ));
            }
        }

        Ok("Healthy".to_string())
    }
}
